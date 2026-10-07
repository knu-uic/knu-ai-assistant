import asyncio
import base64
import json

import httpx
import pytest
from langchain_core.messages import AIMessage, HumanMessage
from langchain_openai import ChatOpenAI
from pydantic import BaseModel

import model


SETTINGS = {"provider": "ollama", "model": "gemma-test", "base_url": "http://local.test/v1", "api_key": ""}
ASYNC_CLIENT = httpx.AsyncClient


def install_native_response(monkeypatch, events, requests):
    def handle(request):
        requests.append(request)
        return httpx.Response(200, text="\n".join(json.dumps(event) for event in events))

    monkeypatch.setattr(
        model.httpx, "AsyncClient",
        lambda **kwargs: ASYNC_CLIENT(transport=httpx.MockTransport(handle), **kwargs),
    )
    monkeypatch.setattr(model, "_active_vlm", lambda: SETTINGS)


def test_native_image_wire_options_and_early_stop(monkeypatch):
    requests = []
    install_native_response(monkeypatch, [
        {"message": {"content": "normal "}, "done": False},
        {"message": {"content": "answer"}, "done": True, "done_reason": "stop", "eval_count": 2},
    ], requests)
    assert model.image_to_text(b"test-image", "image/png", "read this") == "normal answer"
    assert len(requests) == 1
    assert str(requests[0].url) == "http://local.test/api/chat"
    payload = json.loads(requests[0].content)
    assert payload["messages"] == [{
        "role": "user", "content": "read this", "images": [base64.b64encode(b"test-image").decode()],
    }]
    assert payload["think"] is False
    assert payload["truncate"] is False
    assert payload["options"] == {
        "num_predict": 4096, "num_ctx": 8192, "temperature": 0, "top_p": 1,
        "repeat_penalty": 1, "presence_penalty": 0, "frequency_penalty": 0,
    }
    assert "max_thinking_tokens" not in payload
    assert "max_completion_tokens" not in payload


@pytest.mark.parametrize("events,error", [
    ([{"message": {"content": '{"ocrText":"partial'}, "done": True, "done_reason": "length"}], model.ImageOutputTruncated),
    ([{"message": {"content": "partial"}, "done": False}], model.ImageOutputError),
    ([{"message": {"content": ""}, "done": True, "done_reason": "stop"}], model.ImageOutputError),
    ([{"error": "provider failed"}], model.ImageOutputError),
    ([{"message": {"content": "partial"}, "done": True, "done_reason": "unknown"}], model.ImageOutputError),
    ([{"message": {"content": []}}], model.ImageOutputError),
    ([{"message": {"content": "answer"}, "done": True, "done_reason": "stop", "eval_count": 4097}], model.ImageOutputError),
])
def test_native_failures_never_return_partial_or_retry(monkeypatch, events, error):
    requests = []
    install_native_response(monkeypatch, events, requests)
    with pytest.raises(error):
        model.image_to_text(b"image", "image/png", "read")
    assert len(requests) == 1


def test_total_deadline_cancels_even_when_stream_keeps_producing(monkeypatch):
    closed = []

    class EndlessStream(httpx.AsyncByteStream):
        async def __aiter__(self):
            while True:
                await asyncio.sleep(0.005)
                yield b'{"message":{"content":"repeat"},"done":false}\n'

        async def aclose(self):
            closed.append(True)

    monkeypatch.setattr(model, "VLM_TIMEOUT_SECONDS", 0.04)
    monkeypatch.setattr(model, "_active_vlm", lambda: SETTINGS)
    monkeypatch.setattr(
        model.httpx, "AsyncClient", lambda **kwargs: ASYNC_CLIENT(
            transport=httpx.MockTransport(lambda _: httpx.Response(200, stream=EndlessStream())), **kwargs,
        ),
    )
    with pytest.raises(model.ImageAnalysisTimeout):
        model.image_to_text(b"image", "image/png", "read")
    assert closed


@pytest.mark.parametrize("status,body", [(200, "not JSON"), (400, '{"error":"bad request"}')])
def test_native_protocol_failure_does_not_retry(monkeypatch, status, body):
    requests = []

    def handle(request):
        requests.append(request)
        return httpx.Response(status, text=body)

    monkeypatch.setattr(model, "_active_vlm", lambda: SETTINGS)
    monkeypatch.setattr(model.httpx, "AsyncClient", lambda **kwargs: ASYNC_CLIENT(
        transport=httpx.MockTransport(handle), **kwargs,
    ))
    with pytest.raises(model.ImageOutputError):
        model.image_to_text(b"image", "image/png", "read")
    assert len(requests) == 1


def test_native_sync_extractor_can_be_called_inside_async_worker(monkeypatch):
    install_native_response(monkeypatch, [
        {"message": {"content": "answer"}, "done": True, "done_reason": "stop"},
    ], [])

    async def worker():
        return model.image_to_text(b"image", "image/png", "read")

    assert asyncio.run(worker()) == "answer"


@pytest.mark.parametrize("url,expected", [
    ("", "http://127.0.0.1:11434/api/chat"),
    ("https://local.test/proxy/v1/", "https://local.test/proxy/api/chat"),
    ("https://local.test", "https://local.test/api/chat"),
])
def test_native_url_preserves_proxy_prefix(url, expected):
    assert model._ollama_chat_url(url) == expected


def test_ollama_text_wire_limit_survives_structured_output():
    requests = []

    def handle(request):
        requests.append(json.loads(request.content))
        return httpx.Response(200, json={
            "id": "test", "object": "chat.completion", "created": 1, "model": "gemma-test",
            "choices": [{"index": 0, "message": {"role": "assistant", "content": '{"title":"ok"}'}, "finish_reason": "stop"}],
            "usage": {"prompt_tokens": 3, "completion_tokens": 4, "total_tokens": 7},
        })

    class Result(BaseModel):
        title: str

    client = model._OllamaChatOpenAI(
        model="gemma-test", api_key="local", base_url="http://local.test/v1",
        max_tokens=2048, timeout=180, max_retries=0,
        extra_body=model._local_extra_body("ollama"),
        http_client=httpx.Client(transport=httpx.MockTransport(handle)),
    )
    try:
        response = client.with_structured_output(Result, method="json_schema").invoke([HumanMessage(content="read")])
        assert response.title == "ok"
        assert requests[0]["max_tokens"] == 2048
        assert "max_completion_tokens" not in requests[0]
        assert requests[0]["reasoning_effort"] == "none"
        assert requests[0]["response_format"]["type"] == "json_schema"
    finally:
        client.root_client.close()


def test_only_ollama_gets_legacy_token_field():
    client = model._text_llm(SETTINGS)
    assert isinstance(client, model._OllamaChatOpenAI)
    assert client.request_timeout == 180
    assert client.max_retries == 0
    cloud = ChatOpenAI(model="gpt-test", api_key="test", max_tokens=4096)
    payload = cloud._get_request_payload([HumanMessage(content="read")])
    assert payload["max_completion_tokens"] == 4096
    assert "max_tokens" not in payload


def test_non_ollama_image_length_is_rejected(monkeypatch):
    monkeypatch.setattr(model, "_active_vlm", lambda: {**SETTINGS, "provider": "lmstudio"})

    class Client:
        def invoke(self, messages):
            return AIMessage(content="partial", response_metadata={"finish_reason": "length"})

    monkeypatch.setattr(model, "_vlm_client", lambda *args: Client())
    with pytest.raises(model.ImageOutputTruncated):
        model.image_to_text(b"image", "image/png", "read")
