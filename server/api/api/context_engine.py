"""Credential-free adapter to the exact vendored Codmes JavaScript engine."""
from __future__ import annotations

import asyncio
import json
import os
import shutil
from pathlib import Path
from typing import Awaitable, Callable

from fastapi import HTTPException

ENGINE = Path(__file__).resolve().parents[1] / "third_party/codmes-context-engine/bridge.mjs"
_slots = asyncio.Semaphore(4)
_MAX_FRAME = 16 * 1024 * 1024


def node_executable() -> str:
    candidate = os.environ.get("KNU_CONTEXT_NODE") or shutil.which("node")
    if not candidate or not Path(candidate).is_file() or not os.access(candidate, os.X_OK):
        raise HTTPException(503, "맥락 관리용 Node.js 런타임이 없습니다. 서버 설치 상태를 확인해주세요.")
    return str(Path(candidate).resolve())


async def run_engine(payload: dict, compact: Callable[[dict], Awaitable[dict]] | None = None) -> dict:
    # No shell, arbitrary script path, inherited NODE_OPTIONS, model secrets,
    # filesystem sessions, network service, or cross-student process reuse.
    env = {key: os.environ[key] for key in ("PATH", "SystemRoot", "WINDIR") if key in os.environ}
    async with _slots:
        try:
            process = await asyncio.create_subprocess_exec(
                node_executable(), str(ENGINE), stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.DEVNULL,
                env=env, limit=_MAX_FRAME,
            )
        except OSError:
            raise HTTPException(503, "맥락 관리용 Node.js 런타임을 실행할 수 없습니다. 서버 설치 상태를 확인해주세요.") from None
        try:
            async with asyncio.timeout(360):
                async def send(value):
                    frame = (json.dumps(value, ensure_ascii=False) + "\n").encode()
                    if len(frame) > _MAX_FRAME:
                        raise HTTPException(413, "대화가 맥락 관리 처리 한도를 초과했습니다.")
                    process.stdin.write(frame)
                    await process.stdin.drain()

                await send(payload)
                while True:
                    async with asyncio.timeout(15):
                        line = await process.stdout.readline()
                    if not line:
                        raise RuntimeError("Context bridge ended unexpectedly")
                    message = json.loads(line)
                    if message.get("type") == "result":
                        await asyncio.wait_for(process.wait(), 5)
                        if process.returncode:
                            raise RuntimeError("Context bridge failed")
                        return message
                    if message.get("type") != "compact" or compact is None:
                        raise RuntimeError("Invalid context bridge protocol")
                    try:
                        result = await compact(message)
                        await send({"type": "compaction_result", "id": message["id"], "result": result})
                    except asyncio.CancelledError:
                        raise
                    except Exception:
                        # The shared engine handles native -> semantic -> raw fallback.
                        await send({"type": "compaction_result", "id": message["id"], "error": True})
        except HTTPException:
            raise
        except (TimeoutError, OSError, RuntimeError, ValueError):
            raise HTTPException(503, "대화 맥락을 준비하지 못했습니다. 기록은 삭제되지 않았습니다. 잠시 후 다시 시도해주세요.") from None
        finally:
            if process.returncode is None:
                process.kill()
            await process.wait()


async def estimate_request(messages: list[dict], model: str, context_window: int) -> dict:
    return await run_engine({"type": "estimate", "messages": messages, "model": model,
                             "overrides": {"contextWindow": context_window}})


async def check_budget(messages: list[dict], model: str, context_window: int):
    estimate = await estimate_request(messages, model, context_window)
    if estimate["tokens"] > estimate["budget"]["inputBudget"]:
        raise HTTPException(413, "질문·도구 결과가 모델의 맥락 예산을 초과했습니다. 질문을 나누거나 더 큰 맥락의 모델을 선택해주세요. 원본 기록은 유지됩니다.")
