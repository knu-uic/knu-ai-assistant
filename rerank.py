"""BGE-reranker 로컬 cross-encoder 재정렬.

graph.py의 _retrieve에서 vector top-N 후보를 받아 top-K로 추리는 데 쓴다.
모델은 첫 호출에 HuggingFace에서 다운로드되어 HF_HOME(Dockerfile에서 /app/.hf_cache로 설정)에 캐시된다.
프로세스 수명 동안 1회만 로드 (lru_cache 싱글톤).
"""

from __future__ import annotations

import math
import os
from functools import lru_cache
from typing import List

from config import RERANKER_MODEL, RERANKER_MAX_LENGTH


@lru_cache(maxsize=1)
def _get_reranker():
    # import을 lazy 하게: 다른 코드 경로(예: 크롤러)는 torch를 안 쓰는데
    # 모듈 top-level import면 매번 ~수 초 페널티가 붙는다.
    import torch
    from sentence_transformers import CrossEncoder

    # 컨테이너 vCPU 수만큼 BLAS/torch 스레드 풀 확보. OMP_NUM_THREADS 우선,
    # 없으면 os.cpu_count(). Docker Desktop CPU 슬라이더와 docker-compose의
    # cpus 설정이 둘 다 반영되어야 실제 코어 수가 늘어남.
    n_threads = int(os.getenv("OMP_NUM_THREADS") or os.cpu_count() or 4)
    torch.set_num_threads(n_threads)

    return CrossEncoder(RERANKER_MODEL, max_length=RERANKER_MAX_LENGTH)


def warmup() -> None:
    """앱 부팅 시 호출. 모델 로드 + 더미 forward 1회로 첫 질문 latency 제거."""
    _get_reranker().predict([("warmup", "warmup")], show_progress_bar=False)


def rerank_scores(query: str, passages: List[str]) -> List[float]:
    """각 passage의 relevance score 리스트 반환 (입력 순서 유지, sigmoid로 0~1 정규화)."""
    if not passages:
        return []
    pairs = [(query, p) for p in passages]
    # CrossEncoder.predict는 raw logit(numpy array) 반환 — sigmoid로 0~1 변환.
    raw = _get_reranker().predict(pairs, show_progress_bar=False)
    return [1.0 / (1.0 + math.exp(-float(s))) for s in raw]
