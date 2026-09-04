import pytest

from embedding.embed import chunk_text, embed_document_chunks


def test_chunk_boundary_keeps_figure_number_with_inline_description():
    source = "앞 문맥 " * 35 + "[그림 1]\n[그림 설명] 학문기초교양 필터 방법 " + "뒤 문맥 " * 35

    chunks = chunk_text(source, chunk_size=120, overlap=20)
    description_chunks = [chunk for chunk in chunks if "[그림 설명]" in chunk]

    assert description_chunks
    assert all("[그림 1]" in chunk for chunk in description_chunks)


@pytest.mark.parametrize("figure_type", ["attachment_figure", "attachment_hwp_figure"])
def test_every_independent_figure_chunk_keeps_marker(monkeypatch, figure_type):
    class FakeEmbedder:
        def embed_documents(self, values):
            return [[float(index)] for index, _ in enumerate(values)]

    monkeypatch.setattr("embedding.embed.get_embeddings", lambda: FakeEmbedder())
    text = "[그림 3]\n" + ("긴 문맥 설명 " * 80)

    chunks = embed_document_chunks(
        title="수강신청 안내",
        body_content="",
        attachment_contents=[{
            "name": "안내.hwp · 그림 3",
            "text": text,
            "type": figure_type,
        }],
    )

    assert len(chunks) > 1
    assert all("[그림 3]" in chunk[1] for chunk in chunks)


def test_every_body_figure_chunk_keeps_body_marker(monkeypatch):
    class FakeEmbedder:
        def embed_documents(self, values):
            return [[float(index)] for index, _ in enumerate(values)]

    monkeypatch.setattr("embedding.embed.get_embeddings", lambda: FakeEmbedder())
    chunks = embed_document_chunks(
        title="포털 사용 안내",
        body_content="",
        attachment_contents=[{
            "name": "__body__ · 본문 그림 2",
            "text": "[본문 그림 2]\n" + ("메뉴 선택 화면 설명 " * 80),
            "type": "body_figure",
        }],
    )

    assert len(chunks) > 1
    assert all(chunk[3] == "body_figure" for chunk in chunks)
    assert all("[본문 그림 2]" in chunk[1] for chunk in chunks)
