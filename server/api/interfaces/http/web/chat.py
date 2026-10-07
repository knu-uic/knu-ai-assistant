"""학생 개인 모델이 KNU MCP 도구를 선택하는 웹 대화 경로."""
from __future__ import annotations

import json
from urllib.parse import urlsplit

import httpx
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import StreamingResponse

from api.codex_oauth import CODEX_RESPONSES_URL, _codex_headers
from api.deps import portal_student_id, require_user
from api.ratelimit import limiter, user_or_ip
from api.student_llm import get_account, refresh_codex
from api.runtime_settings import load_settings
from api.chat_context import CURRENT_TURN, TurnContext, prepare_context, validate_context
from db import conversations as conversation_repository
from config import RATE_LIMIT_CHAT
from interfaces.http.schemas.chat import ChatMessage, ChatRequest, ChatResponse
from interfaces.mcp.server import _MCP_PRINCIPAL, mcp
from interfaces.http.web.history_tools import TOOLS as HISTORY_TOOLS

router = APIRouter()
_INSTRUCTIONS = (
    "당신은 국립공주대학교 학생을 돕는 KNU PICK입니다. 최신 학교 정보와 개인 정보는 "
    "제공된 KNU 도구로 확인하고, 근거가 없으면 모른다고 답하세요. "
    "신청 링크는 사용자가 신청 방법 또는 링크를 물을 때에만 답변에 포함하세요. "
    "도구 결과에 없는 URL이나 사실을 만들어내지 마세요. "
    "신청·상담 접수 등 쓰기 행동은 사용자가 명시적으로 최종 확인하기 전에는 하지 마세요."
)


def _student(principal: str = Depends(require_user)) -> str:
    student_id = portal_student_id(principal)
    if not student_id:
        raise HTTPException(403, "학생 계정이 필요합니다.")
    return student_id


def _sse(event: str, data: dict) -> str:
    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"


async def _active_account(student_id: str) -> dict:
    account = await get_account(student_id)
    if not account or not account["model"]:
        raise HTTPException(409, "대화에 사용할 개인 LLM 계정과 모델을 먼저 연결해주세요.")
    if account["provider"] == "openai-codex":
        try:
            account = await refresh_codex(student_id, account)
        except (LookupError, httpx.HTTPError) as exc:
            raise HTTPException(409, "Codex 계정 재연결이 필요합니다.") from exc
    return account


def _school_settings() -> dict:
    settings = load_settings()["school_chat"]
    if not settings["enabled"] or not settings["model"]:
        raise HTTPException(409, "학교 제공 대화 모델이 아직 설정되지 않았습니다.")
    if settings["provider"] == "openai":
        if not settings["api_key"]:
            raise HTTPException(409, "학교 OpenAI API 키가 설정되지 않았습니다.")
        return {**settings, "base_url": "https://api.openai.com/v1"}
    if settings["provider"] == "google":
        if not settings["api_key"]:
            raise HTTPException(409, "학교 Gemini API 키가 설정되지 않았습니다.")
        return {**settings, "base_url": "https://generativelanguage.googleapis.com/v1beta/openai"}
    parsed = urlsplit(settings["base_url"])
    if (settings["provider"] not in {"ollama", "lmstudio"} or parsed.scheme != "http"
            or parsed.hostname not in {"127.0.0.1", "localhost", "::1"}
            or parsed.path.rstrip("/") not in {"", "/v1"} or parsed.query or parsed.fragment):
        raise HTTPException(409, "학교 제공 대화 모델의 로컬 주소 설정을 확인해주세요.")
    return {**settings, "base_url": settings["base_url"].rstrip("/").removesuffix("/v1") + "/v1"}


async def _tool_catalog() -> tuple[list[dict], dict]:
    tools = await mcp.get_tools()
    allowed = {}
    definitions = []
    for tool in tools.values():
        # 웹에서는 명시적 승인 흐름을 구현하기 전까지 읽기 도구만 공개한다.
        safe_unannotated = {"knu_prepare_online_counseling", "knu_counseling_job_status"}
        if not tool.enabled or not (
            (tool.annotations and tool.annotations.readOnlyHint) or tool.name in safe_unannotated
        ):
            continue
        allowed[tool.name] = tool
        definitions.append({"type": "function", "name": tool.name,
                            "description": tool.description or "",
                            "strict": False,
                            "parameters": tool.parameters})
    for tool in HISTORY_TOOLS:
        allowed[tool.name] = tool
        definitions.append(tool.definition())
    return definitions, allowed


async def _response(client: httpx.AsyncClient, account: dict, inputs: list[dict],
                    definitions: list[dict], *, instructions: str = _INSTRUCTIONS) -> dict:
    if account["provider"] == "openai":
        url = "https://api.openai.com/v1/responses"
        headers = {"Authorization": f"Bearer {account['secret']['api_key']}"}
    else:
        url = CODEX_RESPONSES_URL
        headers = _codex_headers(account["secret"])
    body = {"model": account["model"], "instructions": instructions,
            "input": inputs, "store": False, "stream": True,
            "include": ["reasoning.encrypted_content"]}
    if definitions:
        body.update({"tools": definitions, "tool_choice": "auto"})
    completed = None
    text_parts: list[str] = []
    async with client.stream("POST", url, headers=headers, json=body) as response:
        response.raise_for_status()
        async for line in response.aiter_lines():
            if not line.startswith("data:"):
                continue
            raw = line[5:].strip()
            if not raw or raw == "[DONE]":
                continue
            try:
                event = json.loads(raw)
            except json.JSONDecodeError:
                continue
            if event.get("type") == "response.completed":
                completed = event.get("response")
            elif event.get("type") == "response.output_text.delta":
                text_parts.append(str(event.get("delta") or ""))
            elif event.get("type") in {"response.failed", "error"}:
                raise RuntimeError("모델 호출이 실패했습니다.")
    if not completed:
        raise RuntimeError("모델 응답을 완료하지 못했습니다.")
    if text_parts and not _answer_text(completed):
        completed["output"] = [*(completed.get("output") or []), {
            "type": "message", "content": [{"type": "output_text", "text": "".join(text_parts)}],
        }]
    return completed


def _answer_text(response: dict) -> str:
    parts = []
    for item in response.get("output") or []:
        if item.get("type") != "message":
            continue
        parts.extend(str(part.get("text") or "") for part in item.get("content") or []
                     if part.get("type") == "output_text")
    return "".join(parts)


async def answer(student_id: str, question: str, history: list[ChatMessage]) -> str:
    account = await _active_account(student_id)
    if account["provider"] == "google":
        return await _chat_completions_answer(student_id, question, history, {
            "provider": "google", "model": account["model"],
            "id": account.get("id", student_id),
            "api_key": account["secret"]["api_key"],
            "base_url": "https://generativelanguage.googleapis.com/v1beta/openai",
        })
    return await _responses_answer(student_id, question, history, account)


async def _responses_answer(student_id: str, question: str, history: list[ChatMessage],
                            account: dict) -> str:
    definitions, allowed = await _tool_catalog()
    async with httpx.AsyncClient(timeout=180) as client:
        inputs, window = await prepare_context(client, account,
            [{"role": m.role, "content": m.content} for m in history if m.content.strip()],
            definitions, _INSTRUCTIONS, question, _response)
        for _ in range(6):
            await validate_context(inputs, account, definitions, _INSTRUCTIONS, window)
            result = await _response(client, account, inputs, definitions)
            output = result.get("output") or []
            calls = [item for item in output if item.get("type") == "function_call"]
            if not calls:
                text = _answer_text(result).strip()
                if not text:
                    raise RuntimeError("모델이 빈 답변을 반환했습니다.")
                return text
            inputs.extend(output)
            for call in calls:
                name = str(call.get("name") or "")
                tool = allowed.get(name)
                if not tool:
                    result_text = json.dumps({"error": "도구를 사용할 수 없습니다."}, ensure_ascii=False)
                else:
                    try:
                        arguments = json.loads(call.get("arguments") or "{}")
                        principal_token = _MCP_PRINCIPAL.set(f"portal:{student_id}")
                        try:
                            tool_result = await tool.run(arguments)
                        finally:
                            _MCP_PRINCIPAL.reset(principal_token)
                        result_text = json.dumps(tool_result.structured_content, ensure_ascii=False, default=str)
                        if tool_result.structured_content is None:
                            result_text = "\n".join(str(part.text) for part in tool_result.content
                                                    if hasattr(part, "text"))
                    except (ValueError, TypeError) as exc:
                        result_text = json.dumps({"error": str(exc)}, ensure_ascii=False)
                inputs.append({"type": "function_call_output",
                               "call_id": call["call_id"], "output": result_text})
    raise RuntimeError("도구 호출 한도를 초과했습니다.")


async def school_answer(student_id: str, question: str, history: list[ChatMessage]) -> str:
    settings = _school_settings()
    if settings["provider"] == "openai":
        return await _responses_answer(student_id, question, history, {
            "provider": "openai", "model": settings["model"],
            "secret": {"api_key": settings["api_key"]},
        })
    return await _chat_completions_answer(student_id, question, history, settings)


async def _chat_completions_answer(student_id: str, question: str,
                                   history: list[ChatMessage], settings: dict) -> str:
    definitions, allowed = await _tool_catalog()
    tools = [{"type": "function", "function": {
        "name": item["name"], "description": item["description"],
        "parameters": item["parameters"],
    }} for item in definitions]
    url = settings["base_url"].rstrip("/") + "/chat/completions"
    async with httpx.AsyncClient(timeout=180) as client:
        history_context, window = await prepare_context(client, settings,
            [{"role": m.role, "content": m.content} for m in history if m.content.strip()],
            definitions, _INSTRUCTIONS, question, _response)
        messages = [{"role": "system", "content": _INSTRUCTIONS}, *history_context]
        for _ in range(6):
            await validate_context(messages[1:], settings, definitions, _INSTRUCTIONS, window)
            body = {"model": settings["model"], "messages": messages, "stream": False}
            if tools:
                body.update({"tools": tools, "tool_choice": "auto"})
            response = await client.post(url, headers={
                "Authorization": f"Bearer {settings.get('api_key') or 'local'}",
            }, json=body)
            response.raise_for_status()
            choices = response.json().get("choices") or []
            if not choices:
                raise RuntimeError("학교 모델이 응답을 반환하지 않았습니다.")
            message = choices[0].get("message") or {}
            calls = message.get("tool_calls") or []
            if not calls:
                content = message.get("content")
                if not isinstance(content, str) or not content.strip():
                    raise RuntimeError("학교 모델이 빈 답변을 반환했습니다.")
                return content.strip()
            messages.append({"role": "assistant", "content": message.get("content"),
                             "tool_calls": calls})
            for call in calls:
                function = call.get("function") or {}
                tool = allowed.get(str(function.get("name") or ""))
                if not tool:
                    result_text = json.dumps({"error": "도구를 사용할 수 없습니다."}, ensure_ascii=False)
                else:
                    try:
                        arguments = json.loads(function.get("arguments") or "{}")
                        principal_token = _MCP_PRINCIPAL.set(f"portal:{student_id}")
                        try:
                            tool_result = await tool.run(arguments)
                        finally:
                            _MCP_PRINCIPAL.reset(principal_token)
                        result_text = json.dumps(tool_result.structured_content, ensure_ascii=False, default=str)
                        if tool_result.structured_content is None:
                            result_text = "\n".join(str(part.text) for part in tool_result.content
                                                    if hasattr(part, "text"))
                    except (ValueError, TypeError) as exc:
                        result_text = json.dumps({"error": str(exc)}, ensure_ascii=False)
                messages.append({"role": "tool", "tool_call_id": call["id"],
                                 "content": result_text})
    raise RuntimeError("도구 호출 한도를 초과했습니다.")


@router.get("/chat/models")
async def chat_models(student_id: str = Depends(_student)) -> dict:
    school = load_settings()["school_chat"]
    available = False
    try:
        _school_settings()
        available = True
    except HTTPException:
        pass
    return {"school": {"available": available,
                       "model": school["model"] if available else ""}}


async def generate_chat(student_id: str, req: ChatRequest) -> dict:
    generate = school_answer if req.source == "school" else answer
    if req.conversation_id is None:
        # Compatibility for older clients; new web/mobile use server-owned history.
        return {"answer": await generate(student_id, req.question, req.history)}
    try:
        async with conversation_repository.conversation_turn(student_id, req) as stored:
            if stored.replayed:
                result = {"answer": stored.answer, "conversation": stored.conversation}
            else:
                context = TurnContext(state=stored.context_state)
                token = CURRENT_TURN.set(context)
                try:
                    from interfaces.http.schemas.chat import ChatMessage
                    history = [ChatMessage.model_construct(**m) for m in stored.conversation["messages"]]
                    text = await generate(student_id, req.question, history)
                    await stored.finish(text, context.state)
                    result = {"answer": text, "conversation": stored.conversation, "context": context.stats}
                finally:
                    CURRENT_TURN.reset(token)
        # Transaction committed before returning or emitting an SSE answer.
        return result
    except conversation_repository.ConversationMissing:
        raise HTTPException(404, "대화 기록을 찾을 수 없습니다.") from None
    except conversation_repository.ConversationConflict as error:
        raise HTTPException(409, str(error)) from None


@router.post("/chat", response_model=ChatResponse, response_model_exclude_none=True)
@limiter.limit(RATE_LIMIT_CHAT, key_func=user_or_ip)
async def chat(request: Request, req: ChatRequest, student_id: str = Depends(_student)) -> dict:
    return await generate_chat(student_id, req)


@router.post("/chat/stream")
@limiter.limit(RATE_LIMIT_CHAT, key_func=user_or_ip)
async def chat_stream(request: Request, req: ChatRequest,
                      student_id: str = Depends(_student)) -> StreamingResponse:
    # SSE 응답 헤더를 보내기 전에 설정 부족을 판정한다.
    if req.source == "school":
        _school_settings()
    else:
        await _active_account(student_id)

    async def events():
        try:
            yield _sse("step", {"label": "KNU 도구와 대화 모델로 확인하고 있어요..."})
            result = await generate_chat(student_id, req)
            text = result["answer"]
            yield _sse("token", {"text": text})
            from fastapi.encoders import jsonable_encoder
            yield _sse("answer", jsonable_encoder(result))
        except HTTPException as error:
            yield _sse("error", {"detail": error.detail, "status": error.status_code})
        except Exception:
            yield _sse("error", {"detail": "답변을 생성하지 못했습니다. 선택한 모델의 연결 상태를 확인해주세요."})
        yield _sse("done", {})

    return StreamingResponse(events(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})
