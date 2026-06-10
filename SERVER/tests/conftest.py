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
# HS256 권장 최소 키 길이(32바이트) 충족 — 짧으면 pyjwt InsecureKeyLengthWarning
os.environ.setdefault("AUTH_JWT_SECRET", "test-secret-for-unit-tests-0123456789ab")


def pytest_configure(config):
    config.addinivalue_line(
        "markers", "real_auth: 인증 우회 없이 실제 토큰 검증을 테스트"
    )


@pytest.fixture(autouse=True)
def bypass_auth(request):
    """보호 라우터 테스트가 토큰 없이 동작하도록 require_user를 대체.
    실제 인증 동작을 검증하는 테스트는 @pytest.mark.real_auth로 우회를 끈다."""
    if "real_auth" in request.keywords:
        yield
        return
    from api.main import app
    from api.deps import require_user

    app.dependency_overrides[require_user] = lambda: "testuser"
    yield
    app.dependency_overrides.pop(require_user, None)


@pytest.fixture(autouse=True)
def mock_pool_lifecycle():
    """AsyncConnectionPool은 open/close 후 재사용 불가.
    테스트마다 lifespan이 pool.open/close를 호출하므로 noop으로 대체한다."""
    from db.pool import pool
    with patch.object(pool, "open", AsyncMock()), \
         patch.object(pool, "close", AsyncMock()):
        yield
