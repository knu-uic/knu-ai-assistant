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
LMS_LOGIN_LOG_PATH = Path(".secrets/lms_login.log")

load_dotenv()

st.set_page_config(page_title="KNU 학생 비서", page_icon="🎓", layout="wide")

# DB에 users 테이블/year 컬럼이 없는 환경(이미 init_db된 구버전 DB)도 흡수.
# 세션 내 한 번만 실행.
if "_schema_ensured" not in st.session_state:
    ensure_users_schema()
    st.session_state._schema_ensured = True


def _start_lms_login():
    LMS_LOGIN_LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    log_file = LMS_LOGIN_LOG_PATH.open("a", encoding="utf-8")
    process = subprocess.Popen(
        [
            sys.executable,
            "lms_login.py",
            "--auto",
            "--timeout",
            "300",
        ],
        cwd=Path.cwd(),
        stdout=log_file,
        stderr=subprocess.STDOUT,
        start_new_session=True,
    )
    log_file.close()
    st.session_state.lms_login_pid = process.pid


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
        st.caption("열리는 브라우저에서 직접 로그인하세요. 비밀번호는 앱이 읽거나 저장하지 않습니다.")
        c1, c2 = st.columns([1, 1])
        with c1:
            if st.button("LMS로 로그인", type="primary", use_container_width=True):
                _start_lms_login()
                st.session_state.lms_login_started = True
                st.rerun()
        with c2:
            if st.button("로그인 완료 확인", use_container_width=True):
                st.rerun()

        if st.session_state.get("lms_login_started"):
            if LMS_STATE_PATH.exists():
                st.success("LMS 로그인이 확인됐어요. 앱을 준비하는 중입니다.")
                st.rerun()
            else:
                st.info("로그인 창에서 LMS 로그인을 완료해 주세요. 완료되면 자동으로 세션이 저장됩니다.")


if not LMS_STATE_PATH.exists():
    _render_login_gate()
    st.stop()

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
