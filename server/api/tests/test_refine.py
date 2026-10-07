from schema import (
    MetadataSchema,
    NoticeApplicationSchema,
    NoticeAudienceSchema,
    NoticePeriodSchema,
    RefinementSchema,
)
import pipelines.refine as refine_module
import model as model_module
from langchain_core.messages import HumanMessage, SystemMessage
import pytest
from model import _local_extra_body


class _FakeStructuredModel:
    def batch(self, _prompts, **_kwargs):
        return [
            RefinementSchema(
                summary="핵심 요약",
                category="취업(진로)",
                periods=[
                    NoticePeriodSchema(
                        kind="application",
                        starts_on="2026-07-20",
                        ends_on="2026-08-04",
                        source_text="2026. 7. 20.부터 8. 4.까지 신청",
                        confidence=0.98,
                    )
                ],
                audiences=[
                    NoticeAudienceSchema(
                        kind="enrollment_status",
                        value="재학생",
                        source_text="재학생 대상",
                        confidence=0.99,
                    )
                ],
                application=NoticeApplicationSchema(
                    method="온라인 신청",
                    evidence={"method": "온라인으로 신청"},
                ),
            )
        ]


class _FakeLlm:
    def __init__(self):
        self.schema = None
        self.kwargs = None

    def with_structured_output(self, schema, **kwargs):
        self.schema = schema
        self.kwargs = kwargs
        return _FakeStructuredModel()


def test_local_refine_extracts_metadata_without_regenerating_original(monkeypatch):
    fake_llm = _FakeLlm()
    monkeypatch.setattr(refine_module, "get_refine_llm", lambda: fake_llm)
    monkeypatch.setattr(refine_module, "VLM_PROVIDER", "local")

    original_content = "원문은 모델 출력이 아니라 crawler 결과를 그대로 보존해야 한다."
    refined = refine_module.refine(
        [
            {
                "title": "WEST 모집",
                "url": "https://example.test/west",
                "date": "2026-07-29",
                "content": original_content,
                "body_content": original_content,
                "assets": [],
                "extra": {"source": "test"},
            }
        ]
    )

    assert fake_llm.schema is RefinementSchema
    assert fake_llm.kwargs == {"method": "json_schema"}
    assert len(refined) == 1

    document, assets, extra = refined[0]
    assert isinstance(document, MetadataSchema)
    assert document.title == "WEST 모집"
    assert document.content == original_content
    assert document.url == "https://example.test/west"
    assert document.summary == "핵심 요약"
    assert document.start_date == "2026-07-20"
    assert document.end_date == "2026-08-04"
    assert document.target == ["재학생"]
    assert "topics" not in type(document).model_fields
    assert "series_key" not in type(document).model_fields
    assert "extraction_confidence" not in type(document).model_fields
    assert document.periods[0].source_text == "2026. 7. 20.부터 8. 4.까지 신청"
    assert document.application.method == "온라인 신청"
    assert assets == []
    assert extra == {"source": "test"}


def test_ollama_refine_uses_native_json_schema(monkeypatch):
    monkeypatch.setattr(
        refine_module,
        "load_settings",
        lambda: {"refine": {"provider": "ollama"}},
    )

    assert refine_module._structured_output_kwargs() == {"method": "json_schema"}


def test_refinement_json_schema_bounds_local_model_output():
    schema = RefinementSchema.model_json_schema()
    properties = schema["properties"]

    assert properties["summary"]["maxLength"] == 700
    assert "topics" not in properties
    assert "series_key" not in properties
    assert "extraction_confidence" not in properties
    assert properties["periods"]["maxItems"] == 12
    assert properties["audiences"]["maxItems"] == 12

    application_ref = properties["application"]["$ref"].rsplit("/", 1)[-1]
    application = schema["$defs"][application_ref]["properties"]
    method_string = next(
        branch for branch in application["method"]["anyOf"]
        if branch.get("type") == "string"
    )
    assert method_string["maxLength"] == 500
    assert application["required_documents"]["maxItems"] == 20
    assert application["required_documents"]["items"]["maxLength"] == 300
    assert application["evidence"]["maxProperties"] == 12
    assert application["evidence"]["additionalProperties"]["maxLength"] == 800


def test_refine_provider_is_independent_from_image_provider(monkeypatch):
    monkeypatch.setattr(refine_module, "VLM_PROVIDER", "google")
    monkeypatch.setattr(
        refine_module,
        "load_settings",
        lambda: {"vlm": {"provider": "google"}, "refine": {"provider": "lmstudio"}},
    )

    assert refine_module._structured_output_kwargs() == {"method": "json_schema"}


def test_refine_llm_selects_refine_settings_not_image_settings(monkeypatch):
    refine_settings = {"provider": "ollama", "model": "notice-model", "base_url": "", "api_key": ""}
    monkeypatch.setattr(
        model_module,
        "load_settings",
        lambda: {"vlm": {"provider": "google", "model": "image-model"}, "refine": refine_settings},
    )
    monkeypatch.setattr(model_module, "_text_llm", lambda settings: settings)
    assert model_module.get_refine_llm() is refine_settings


def test_codex_refine_uses_login_provider_and_validates_json(monkeypatch):
    monkeypatch.setattr(
        model_module,
        "load_settings",
        lambda: {"refine": {"provider": "openai-codex", "model": "codex-model"}},
    )
    calls = []
    def fake_codex_response(prompt, *, model, instructions):
        calls.append((prompt, model, instructions))
        return '{"summary":"신청 안내","category":"수강"}'
    monkeypatch.setattr(model_module, "codex_response", fake_codex_response)

    client = model_module.get_refine_llm().with_structured_output(RefinementSchema)
    result = client.invoke([SystemMessage(content="근거만 사용"), HumanMessage(content="공지")])
    assert result.summary == "신청 안내"
    assert result.category == "수강"
    assert calls[0][1] == "codex-model"
    assert calls[0][0] == "공지"
    assert "근거만 사용" in calls[0][2]
    assert "JSON" in calls[0][2]

    monkeypatch.setattr(model_module, "codex_response", lambda *_args, **_kwargs: "not JSON")
    with pytest.raises(model_module.RefineOutputError):
        client.invoke([HumanMessage(content="공지")])


def test_local_provider_uses_native_thinking_switch():
    assert _local_extra_body("ollama") == {"reasoning_effort": "none"}
    assert _local_extra_body("lmstudio") == {
        "chat_template_kwargs": {"enable_thinking": False}
    }
