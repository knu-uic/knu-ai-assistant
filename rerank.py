"""BGE-reranker-v2-m3 로컬 cross-encoder 재정렬.

graph.py의 _retrieve_with_rerank에서 vector top-15 후보를 받아 top-3으로 추리는 데 쓴다.
모델은 ~600MB, 첫 호출에 HuggingFace에서 다운로드되어 HF_HOME 캐시에 보존된다.
프로세스 수명 동안 1회만 로드 (lru_cache 싱글톤).
"""

# === [seungwon/bge-reranker] 파일 전체 신규 ===
from __future__ import annotations

import math
from functools import lru_cache
from typing import List

# 원래 seungwon/bge-reranker 브랜치는 config.py에서 import했으나,
# 한정우 브랜치 환경(로컬 모델 셋업)을 건드리지 않기 위해 모듈 상수로 인라인.
RERANKER_MODEL = "BAAI/bge-reranker-v2-m3"
RERANKER_MAX_LENGTH = 512


@lru_cache(maxsize=1)
def _get_reranker():
    # import을 lazy 하게: 다른 코드 경로(예: 크롤러)는 torch를 안 쓰는데
    # 모듈 top-level import면 매번 ~수 초 페널티가 붙는다.
    from sentence_transformers import CrossEncoder
    return CrossEncoder(RERANKER_MODEL, max_length=RERANKER_MAX_LENGTH)


def rerank_scores(query: str, passages: List[str]) -> List[float]:
    """각 passage의 relevance score 리스트 반환 (입력 순서 유지, sigmoid로 0~1 정규화)."""
    if not passages:
        return []
    pairs = [(query, p) for p in passages]
    # CrossEncoder.predict는 raw logit(numpy array) 반환 — sigmoid로 0~1 변환.
    raw = _get_reranker().predict(pairs, show_progress_bar=False)
    return [1.0 / (1.0 + math.exp(-float(s))) for s in raw]
