"""RAG 파이프라인 튜닝 상수와 환경 변수 일괄 관리.

기존에 embed.py / graph.py / rerank.py / db.py / model.py 5곳에 흩어져 있던
설정 값을 한 곳으로 모은다. 새 상수 추가 시 이 파일 + 호출 모듈만 손대면 된다.

`.env`/docker-compose 환경 변수는 모듈 import 시점에 로딩되므로,
이 모듈을 다른 모듈보다 먼저 import해도 안전하다.
"""

import os

from dotenv import load_dotenv

load_dotenv()

# ── DB ────────────────────────────────────────────────────────────────────
DB_USER = os.getenv("DB_USER", "knu-uic")
DB_NAME = os.getenv("DB_NAME", "knu-uic")
DB_HOST = os.getenv("DB_HOST", "db")
DB_PORT = os.getenv("DB_PORT", "5432")
DB_PASSWORD = os.getenv("DB_PASSWORD")
DB_URL = f"postgresql://{DB_USER}:{DB_PASSWORD}@{DB_HOST}:{DB_PORT}/{DB_NAME}"

# ── Provider 토글 ────────────────────────────────────────────────────────
# .env 또는 docker-compose 환경변수에서 LLM_PROVIDER=openai|gemini 로 전환.
# 토글 시 임베딩 모델 자체가 바뀌므로 전체 재크롤링이 필수다 (init_db로 vector 차원 재생성).
LLM_PROVIDER = os.getenv("LLM_PROVIDER", "openai").lower()
if LLM_PROVIDER not in ("openai", "gemini"):
    raise ValueError(f"LLM_PROVIDER must be 'openai' or 'gemini', got {LLM_PROVIDER!r}")

OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
# Gemini 변수명 두 관습(GOOGLE_API_KEY / GEMINI_API_KEY) 모두 수용.
GOOGLE_API_KEY = os.getenv("GOOGLE_API_KEY") or os.getenv("GEMINI_API_KEY")

# ── 임베딩 / LLM / VLM 모델명 (provider별) ───────────────────────────────
# 차원은 두 provider 모두 1536으로 통일 — OpenAI text-embedding-3-small 네이티브 차원.
# Gemini는 Matryoshka로 3072→1536 truncate. HNSW vector(EMBEDDING_DIM)도 이 값을 참조한다.
EMBEDDING_DIM = 1536
CHUNK_SIZE = 800              # 한국어 공지 기준 sliding window.
CHUNK_OVERLAP = 100

if LLM_PROVIDER == "openai":
    EMBEDDING_MODEL = "text-embedding-3-small"
    LLM_MODEL = "gpt-4o-mini"
    VLM_MODEL = "gpt-4o-mini"
else:  # gemini
    EMBEDDING_MODEL = "gemini-embedding-2-preview"
    LLM_MODEL = "gemini-2.5-flash"
    VLM_MODEL = "gemini-2.5-flash"

# ── Reranker (rerank.py) ─────────────────────────────────────────────────
# 사용자 결정: BGE-reranker-v2-m3 유지 (이전 다운그레이드를 되돌림).
RERANKER_MODEL = "BAAI/bge-reranker-v2-m3"
RERANKER_MAX_LENGTH = 512

# ── Retrieval (graph.py) ─────────────────────────────────────────────────
RERANK_CANDIDATES = 15        # vector 1차 후보 수
RERANK_TOP_N = 3            # cross-encoder 통과 후 최종 컨텍스트 수
