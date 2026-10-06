"""BGE-reranker-v2-m3 로컬 cross-encoder 또는 Jina API 기반 재정렬.

현재 retrieval 흐름:

vector top50 chunks
→ cross-encoder / jina rerank
→ evidence top5 chunks
→ support document top3 packing
"""
from __future__ import annotations

import os
import json
import math
import urllib.request
import urllib.error
from functools import lru_cache
from typing import List

from api.runtime_settings import load_settings
from model import _get_reranker
from retrieval.reranker_runtime import local_model_path


@lru_cache(maxsize=2)
def _reranker_model(model: str, max_length: int):
    """CrossEncoder singleton wrapper."""
    if local_model_path(model) is None:
        raise RuntimeError("로컬 리랭커 모델이 설치되지 않았습니다.")
    return _get_reranker(model, max_length)


def clear_reranker_runtime_cache() -> None:
    from model import clear_reranker_cache

    _reranker_model.cache_clear()
    clear_reranker_cache()


def _sigmoid(x: float) -> float:
    """Overflow-safe sigmoid."""
    if x >= 0:
        z = math.exp(-x)
        return 1.0 / (1.0 + z)
    z = math.exp(x)
    return z / (1.0 + z)


def _identity(value):
    """CrossEncoder의 모델 기본 sigmoid를 끄고 원시 logit을 받는다."""
    return value


def _rerank_jina(query: str, passages: List[str]) -> List[float]:
    """Jina Reranker v3 API를 호출하여 입력 순서 그대로 0~1 점수로 변환하여 리턴한다."""
    api_key = os.getenv("JINA_API_KEY")
    if not api_key:
        raise ValueError("JINA_API_KEY가 환경 변수에 설정되어 있지 않습니다.")

    url = "https://api.jina.ai/v1/rerank"
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {api_key}",
        "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    }

    payload = {
        "model": "jina-reranker-v3",
        "query": query,
        "documents": passages,
        "top_n": len(passages),
        "return_documents": True
    }

    req = urllib.request.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers=headers,
        method="POST"
    )

    try:
        with urllib.request.urlopen(req) as response:
            res_body = response.read().decode("utf-8")
            data = json.loads(res_body)
            # Jina API 응답의 relevance_score를 원래 passages 배열 순서대로 정렬하여 매핑
            scores_map = {item['index']: item['relevance_score'] for item in data['results']}
            return [scores_map[i] for i in range(len(passages))]
    except urllib.error.HTTPError as e:
        error_body = e.read().decode("utf-8")
        raise Exception(f"Jina Reranker API HTTP Error {e.code}: {error_body}")
    except Exception as e:
        raise Exception(f"Jina Reranker API Call Failed: {e}")


def _rerank_local(
    query: str,
    passages: List[str],
    *,
    model: str,
    max_length: int,
) -> List[float]:
    """로컬 CrossEncoder를 호출하여 0~1 점수로 변환하여 리턴한다."""
    pairs = [(query, p) for p in passages]
    raw = _reranker_model(model, max_length).predict(
        pairs,
        show_progress_bar=False,
        activation_fn=_identity,
    )
    return [_sigmoid(float(s)) for s in raw]


def rerank_scores(query: str, passages: List[str]) -> List[float]:
    """각 passage의 semantic relevance score 반환.

    Server Manager 런타임 설정에 따라 로컬 CrossEncoder를 사용.
    """
    if not passages:
        return []

    settings = load_settings()["reranker"]
    if not settings["enabled"]:
        raise RuntimeError("로컬 리랭커가 비활성화되어 있습니다.")
    provider = str(settings["provider"] or "local").lower().strip()
    if provider == "jina":
        return _rerank_jina(query, passages)
    elif provider == "local":
        return _rerank_local(
            query,
            passages,
            model=str(settings["model"]),
            max_length=int(settings["max_length"]),
        )
    else:
        raise ValueError(f"지원하지 않는 RERANKER_PROVIDER입니다: {provider}")
