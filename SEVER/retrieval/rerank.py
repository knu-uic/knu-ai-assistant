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

import config
from model import _get_reranker


@lru_cache(maxsize=1)
def _reranker_model():
    """CrossEncoder singleton wrapper."""
    return _get_reranker()


def _sigmoid(x: float) -> float:
    """Overflow-safe sigmoid."""
    if x >= 0:
        z = math.exp(-x)
        return 1.0 / (1.0 + z)
    z = math.exp(x)
    return z / (1.0 + z)


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


def _rerank_local(query: str, passages: List[str]) -> List[float]:
    """로컬 CrossEncoder를 호출하여 0~1 점수로 변환하여 리턴한다."""
    pairs = [(query, p) for p in passages]
    raw = _reranker_model().predict(
        pairs,
        show_progress_bar=False,
    )
    return [_sigmoid(float(s)) for s in raw]


def rerank_scores(query: str, passages: List[str]) -> List[float]:
    """각 passage의 semantic relevance score 반환.

    config.RERANKER_PROVIDER 설정에 따라 Jina API 혹은 로컬 CrossEncoder 사용.
    """
    if not passages:
        return []

    provider = (config.RERANKER_PROVIDER or "local").lower().strip()
    if provider == "jina":
        return _rerank_jina(query, passages)
    elif provider == "local":
        return _rerank_local(query, passages)
    else:
        raise ValueError(f"지원하지 않는 RERANKER_PROVIDER입니다: {provider}")

