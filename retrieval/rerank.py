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
import os
import json
import urllib.request
import urllib.error
from typing import List

def rerank_scores(query: str, passages: List[str]) -> List[float]:
    """각 passage의 semantic relevance score 반환.

    Jina Reranker v3 API를 호출하여 입력 순서 그대로 0~1 점수로 변환하여 리턴한다.
    """
    if not passages:
        return []

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

