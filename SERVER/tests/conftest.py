import os
from unittest.mock import AsyncMock, patch

import pytest

# Minimum env vars needed so db/schema.py and model.py can be imported
# without a live .env file during unit tests.
os.environ.setdefault("EMBEDDING_DIM", "768")
os.environ.setdefault("DB_PASSWORD", "test")
os.environ.setdefault("DB_USER", "knu-uic")
os.environ.setdefault("DB_NAME", "knu-uic")
os.environ.setdefault("DB_PORT", "5432")
os.environ.setdefault("EMBEDDING_PROVIDER", "local")
os.environ.setdefault("RERANKER_PROVIDER", "local")
os.environ.setdefault("VLM_PROVIDER", "local")


@pytest.fixture(autouse=True)
def mock_pool_lifecycle():
    """AsyncConnectionPool은 open/close 후 재사용 불가.
    테스트마다 lifespan이 pool.open/close를 호출하므로 noop으로 대체한다."""
    from db.pool import pool
    with patch.object(pool, "open", AsyncMock()), \
         patch.object(pool, "close", AsyncMock()):
        yield
