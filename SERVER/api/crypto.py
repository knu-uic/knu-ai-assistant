"""포털 비밀번호 잡 전달용 대칭 암호화 (Fernet).

비밀번호는 서버 어디에도 저장하지 않는다. API → Redis 잡 페이로드 → 워커
구간에서만 암호문으로 존재하고, 워커가 복호화해 쓰고 폐기한다.
이 암호화는 Redis 덤프/로그 단독 유출을 막는 수준이다 — 키(env)와 Redis가
같이 털리면 보호 못 함 (위협모델은 설계문서 rev2 B6 참조).

키 생성: python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
"""
from cryptography.fernet import Fernet

from config import PORTAL_SYNC_ENC_KEY


def _fernet() -> Fernet:
    if not PORTAL_SYNC_ENC_KEY:
        raise RuntimeError(
            "PORTAL_SYNC_ENC_KEY 환경변수가 없습니다. "
            "Fernet.generate_key()로 생성해 .env에 설정하세요."
        )
    return Fernet(PORTAL_SYNC_ENC_KEY.encode())


def encrypt_secret(plain: str) -> str:
    return _fernet().encrypt(plain.encode()).decode()


def decrypt_secret(token: str) -> str:
    return _fernet().decrypt(token.encode()).decode()
