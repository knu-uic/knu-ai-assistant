from schema import MetadataSchema, RefinementSchema
import pipelines.refine as refine_module


class _FakeStructuredModel:
    def batch(self, _prompts, **_kwargs):
        return [
            RefinementSchema(
                summary="핵심 요약",
                target=["재학생"],
                start_date="2026-07-20",
                end_date="2026-08-04",
                category="취업(진로)",
                keywords=["WEST"],
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
    monkeypatch.setattr(refine_module, "get_llm", lambda: fake_llm)
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
    assert assets == []
    assert extra == {"source": "test"}
