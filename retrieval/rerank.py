"""BGE-reranker-v2-m3 로컬 cross-encoder 재정렬.

현재 retrieval 흐름:

vector top50 chunks
→ cross-encoder rerank
→ evidence top5 chunks
→ support document top3 packing

reranker는 body chunk / attachment chunk를 구분하지 않고
semantic relevance 기준으로 재정렬한다.

모델은 첫 호출 시 HuggingFace에서 다운로드되며,
프로세스 수명 동안 singleton으로 1회만 로드된다.
"""
from __future__ import annotations

import math
from typing import List
from functools import lru_cache

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


def rerank_scores(query: str, passages: List[str]) -> List[float]:
    """각 passage의 semantic relevance score 반환.

    입력 순서를 유지하며:
    - raw logit
    - sigmoid normalization

    을 거쳐 0~1 score로 변환한다.

    passage는:
    - body chunk
    - attachment chunk

    모두 가능하다.
    """
    if not passages:
        return []
    pairs = [(query, p) for p in passages]
    # CrossEncoder.predict는 raw logit(numpy array) 반환 — sigmoid로 0~1 변환.
    raw = _reranker_model().predict(
        pairs,
        show_progress_bar=False,
    )

    return [_sigmoid(float(s)) for s in raw]
