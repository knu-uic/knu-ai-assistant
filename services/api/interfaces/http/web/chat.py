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
from config import RATE_LIMIT_CHAT
from interfaces.http.schemas.chat import ChatMessage, ChatRequest, ChatResponse
from interfaces.mcp.server import _MCP_PRINCIPAL, mcp

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
    return definitions, allowed


async def _response(client: httpx.AsyncClient, account: dict, inputs: list[dict],
                    definitions: list[dict]) -> dict:
    if account["provider"] == "openai":
        url = "https://api.openai.com/v1/responses"
        headers = {"Authorization": f"Bearer {account['secret']['api_key']}"}
    else:
        url = CODEX_RESPONSES_URL
        headers = _codex_headers(account["secret"])
    body = {"model": account["model"], "instructions": _INSTRUCTIONS,
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
            "api_key": account["secret"]["api_key"],
            "base_url": "https://generativelanguage.googleapis.com/v1beta/openai",
        })
    return await _responses_answer(student_id, question, history, account)


async def _responses_answer(student_id: str, question: str, history: list[ChatMessage],
                            account: dict) -> str:
    definitions, allowed = await _tool_catalog()
    inputs = [{"role": m.role, "content": m.content} for m in history[-12:]
              if m.role in {"user", "assistant"} and m.content.strip()]
    inputs.append({"role": "user", "content": question})
    async with httpx.AsyncClient(timeout=180) as client:
        for _ in range(6):
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
    messages: list[dict] = [{"role": "system", "content": _INSTRUCTIONS}]
    messages.extend({"role": m.role, "content": m.content} for m in history[-12:]
                    if m.role in {"user", "assistant"} and m.content.strip())
    messages.append({"role": "user", "content": question})
    tools = [{"type": "function", "function": {
        "name": item["name"], "description": item["description"],
        "parameters": item["parameters"],
    }} for item in definitions]
    url = settings["base_url"].rstrip("/") + "/chat/completions"
    async with httpx.AsyncClient(timeout=180) as client:
        for _ in range(6):
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


@router.post("/chat", response_model=ChatResponse)
@limiter.limit(RATE_LIMIT_CHAT, key_func=user_or_ip)
async def chat(request: Request, req: ChatRequest, student_id: str = Depends(_student)) -> dict:
    generate = school_answer if req.source == "school" else answer
    return {"answer": await generate(student_id, req.question, req.history)}


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
            generate = school_answer if req.source == "school" else answer
            text = await generate(student_id, req.question, req.history)
            yield _sse("token", {"text": text})
            yield _sse("answer", {"answer": text})
        except Exception:
            yield _sse("error", {"detail": "답변을 생성하지 못했습니다. 선택한 모델의 연결 상태를 확인해주세요."})
        yield _sse("done", {})

    return StreamingResponse(events(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})
