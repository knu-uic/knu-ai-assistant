from retrieval import rerank
from retrieval.reranker_runtime import _directory_bytes


def test_local_reranker_applies_sigmoid_once_to_raw_logits(monkeypatch):
    class FakeCrossEncoder:
        def predict(self, pairs, **kwargs):
            assert pairs == [("질문", "관련 문장"), ("질문", "무관 문장")]
            assert kwargs["activation_fn"](3.0) == 3.0
            return [6.0, -6.0]

    monkeypatch.setattr(
        rerank,
        "load_settings",
        lambda: {"reranker": {
            "enabled": True,
            "provider": "local",
            "model": "BAAI/bge-reranker-v2-m3",
            "max_length": 512,
        }},
    )
    monkeypatch.setattr(rerank, "_reranker_model", lambda *_args: FakeCrossEncoder())

    scores = rerank.rerank_scores("질문", ["관련 문장", "무관 문장"])

    assert scores[0] > 0.99
    assert scores[1] < 0.01


def test_reranker_cache_size_follows_shared_blob_symlinks(tmp_path):
    shared_blob = tmp_path / "shared-model.safetensors"
    shared_blob.write_bytes(b"x" * 2048)
    model_cache = tmp_path / "model-cache"
    model_cache.mkdir()
    (model_cache / "model.safetensors").symlink_to(shared_blob)

    assert _directory_bytes(model_cache) == 2048
