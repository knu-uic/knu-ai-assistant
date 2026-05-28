"""KNU 지능형 학생 비서 진입점. st.navigation으로 4페이지 라우팅."""

import sitecustomize  # noqa: F401  # project-level pycache routing

import json
from pathlib import Path
import subprocess
import sys

import streamlit as st
from dotenv import load_dotenv

from db import ensure_users_schema
from ui import CURRENT_STUDENT_ID_KEY, get_current_user, render_sidebar_user_card

LMS_STATE_PATH = Path(".secrets/lms_storage_state.json")
LMS_CURRENT_USER_PATH = Path(".secrets/lms_current_user.json")

load_dotenv()

st.set_page_config(page_title="KNU 학생 비서", page_icon="🎓", layout="wide")

# DB에 users 테이블/year 컬럼이 없는 환경(이미 init_db된 구버전 DB)도 흡수.
# 세션 내 한 번만 실행.
if "_schema_ensured" not in st.session_state:
    ensure_users_schema()
    st.session_state._schema_ensured = True


def _login_lms_with_credentials(username: str, password: str):
    return subprocess.run(
        [
            sys.executable,
            "lms_login.py",
            "--username",
            username,
            "--password-stdin",
            "--timeout",
            "60",
        ],
        cwd=Path.cwd(),
        input=password + "\n",
        capture_output=True,
        text=True,
        timeout=90,
        check=False,
    )


def _sync_portal_graduation(username: str, password: str):
    return subprocess.run(
        [
            sys.executable,
            "knuis_sync.py",
            "--username",
            username,
            "--password-stdin",
        ],
        cwd=Path.cwd(),
        input=password + "\n",
        capture_output=True,
        text=True,
        timeout=120,
        check=False,
    )


def _sync_lms_at_startup():
    result = subprocess.run(
        [sys.executable, "lms_sync.py"],
        cwd=Path.cwd(),
        capture_output=True,
        text=True,
        timeout=120,
        check=False,
    )
    if result.returncode != 0:
        return result

    if LMS_CURRENT_USER_PATH.exists():
        try:
            current_user = json.loads(LMS_CURRENT_USER_PATH.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            current_user = {}
        student_id = current_user.get("student_id")
        if student_id:
            st.session_state[CURRENT_STUDENT_ID_KEY] = student_id
    return result


def _render_login_gate():
    with st.sidebar:
        st.markdown("### 🎓 KNU 학생 비서")
        st.caption("공주대학교")

    st.title("KNU 학생 비서 로그인")
    st.caption("공주대학교 LMS 계정으로 로그인하면 프로필과 할 일을 자동으로 불러옵니다.")

    with st.container(border=True):
        st.subheader("LMS 로그인")
        st.caption("계정 정보는 로그인 검증에만 사용하고 저장하지 않습니다. 성공하면 LMS 세션 쿠키만 저장합니다.")
        with st.form("lms_login_form"):
            username = st.text_input("LMS 아이디")
            password = st.text_input("LMS 비밀번호", type="password")
            submitted = st.form_submit_button("로그인", type="primary", use_container_width=True)

        if submitted:
            if not username.strip() or not password:
                st.warning("아이디와 비밀번호를 입력해 주세요.")
            else:
                with st.spinner("LMS 계정을 확인하는 중이에요."):
                    result = _login_lms_with_credentials(username.strip(), password)

                if result.returncode == 0 and LMS_STATE_PATH.exists():
                    # KNUIS 포털 졸업자가진단 및 학적 정보 연동
                    with st.spinner("통합정보시스템 학적 정보 및 졸업 학점을 연동하고 있어요."):
                        portal_result = _sync_portal_graduation(username.strip(), password)
                    if portal_result.returncode != 0:
                        st.toast("통합정보시스템 연동 실패", icon="⚠️")
                    
                    st.success("LMS 로그인이 확인됐어요. 앱을 준비합니다.")
                    st.session_state.lms_startup_synced = False
                    st.rerun()
                else:
                    message = result.stderr.strip() or result.stdout.strip() or "LMS 로그인에 실패했어요."
                    st.error(message)


if not LMS_STATE_PATH.exists():
    _render_login_gate()
    st.stop()

# Canvas Access Token 백그라운드 비동기 발급 (메인 화면 진입 후 조용히 처리)
token_file = LMS_STATE_PATH.parent / "lms_canvas_token.txt"
if not token_file.exists():
    import threading
    def _run_bg_token_generation():
        subprocess.run(
            [sys.executable, "lms_login.py", "--token-only"],
            cwd=Path.cwd(),
            capture_output=True,
            text=True,
        )
    if "_bg_token_thread_started" not in st.session_state:
        st.session_state._bg_token_thread_started = True
        t = threading.Thread(target=_run_bg_token_generation, daemon=True)
        t.start()

if not st.session_state.get("lms_startup_synced"):
    with st.spinner("LMS 프로필과 할 일을 불러오는 중이에요."):
        sync_result = _sync_lms_at_startup()
    st.session_state.lms_startup_synced = True
    if sync_result.returncode == 0:
        st.session_state.lms_synced_this_session = True
        st.toast(sync_result.stdout.strip() or "LMS 동기화 완료")
    else:
        st.warning(sync_result.stderr.strip() or sync_result.stdout.strip() or "LMS 동기화에 실패했어요.")

# 사이드바 상단 브랜딩.
with st.sidebar:
    st.markdown("### 🎓 KNU 학생 비서")
    st.caption("공주대학교")

# 사이드바 하단 사용자 카드. 페이지 본문 이전에 그려둔다.
user = get_current_user()
render_sidebar_user_card(user)

# 로그아웃 버튼 추가 (DB 유저는 남겨두고 로컬 세션 캐시 파일만 소거)
with st.sidebar:
    st.write("")
    if st.button("로그아웃 🚪", use_container_width=True, key="logout_sidebar_btn"):
        token_file = LMS_STATE_PATH.parent / "lms_canvas_token.txt"
        for path in (LMS_STATE_PATH, LMS_CURRENT_USER_PATH, token_file):
            if path.exists():
                try:
                    path.unlink()
                except Exception:
                    pass
        st.session_state.clear()
        st.rerun()

home_page = st.Page("app_pages/home.py", title="홈", icon=":material/home:", default=True)
notices_page = st.Page("app_pages/notices.py", title="공지사항", icon=":material/notifications:")
lms_page = st.Page("app_pages/lms.py", title="LMS", icon=":material/school:")
chatbot_page = st.Page("app_pages/chatbot.py", title="AI 챗봇", icon=":material/smart_toy:")
profile_page = st.Page("app_pages/profile.py", title="프로필 / 설정", icon=":material/settings:")

pg = st.navigation({
    "메뉴": [home_page, notices_page, lms_page, chatbot_page],
    "계정": [profile_page],
})
pg.run()
