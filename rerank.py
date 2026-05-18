"""BGE-reranker-v2-m3 로컬 cross-encoder 재정렬.

graph.py의 _retrieve_with_rerank에서 vector top-15 후보를 받아 top-3으로 추리는 데 쓴다.
모델은 ~600MB, 첫 호출에 HuggingFace에서 다운로드되어 HF_HOME 캐시에 보존된다.
프로세스 수명 동안 1회만 로드 (lru_cache 싱글톤).
"""
from model import _get_reranker
from __future__ import annotations
import math
from typing import List


def rerank_scores(query: str, passages: List[str]) -> List[float]:
    """각 passage의 relevance score 리스트 반환 (입력 순서 유지, sigmoid로 0~1 정규화)."""
    if not passages:
        return []
    pairs = [(query, p) for p in passages]
    # CrossEncoder.predict는 raw logit(numpy array) 반환 — sigmoid로 0~1 변환.
    raw = _get_reranker().predict(pairs, show_progress_bar=False)
    return [1.0 / (1.0 + math.exp(-float(s))) for s in raw]
