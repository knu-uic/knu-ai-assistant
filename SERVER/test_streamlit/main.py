"""서버 테스트용 Streamlit 진입점.

실제 제품 앱은 Flutter이며, 이 모듈은 백엔드/RAG/동기화 동작을 검증하기 위한
보조 UI다.
"""

import sitecustomize  # noqa: F401  # project-level pycache routing

import subprocess
import sys
from pathlib import Path

import streamlit as st
from dotenv import load_dotenv

from db import ensure_users_schema
from integrations import get_student_id, lms_linked, portal_linked
from test_streamlit.ui import get_current_user, render_sidebar_user_card

def _sync_lms_at_startup():
    result = subprocess.run(
        [sys.executable, "sync/lms_sync.py"],
        cwd=Path.cwd(),
        capture_output=True,
        text=True,
        timeout=120,
        check=False,
    )
    # lms_sync가 LMS current-user 파일을 갱신 → 세션 신원 하이드레이트.
    get_student_id()
    return result


load_dotenv()


def main():
    st.set_page_config(page_title="KNU 학생 비서", page_icon="🎓", layout="wide")

    # DB에 users 테이블/컬럼이 없는 환경(구버전 DB)도 흡수. 세션 내 한 번만.
    if "_schema_ensured" not in st.session_state:
        ensure_users_schema()
        st.session_state._schema_ensured = True

    # LMS 연동된 경우에만 세션 1회 백그라운드 동기화(익명 사용자는 건너뜀).
    if lms_linked() and not st.session_state.get("lms_startup_synced"):
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

    # 사이드바 하단 사용자 카드(익명이면 '이름 미설정'). 페이지 본문 이전에 그려둔다.
    user = get_current_user()
    render_sidebar_user_card(user)

    # ── 조건부 네비게이션 ──────────────────────────────────────────
    # 홈/공지/챗봇/설정은 항상. LMS·포털은 연동된 경우에만 노출.
    home_page = st.Page("test_streamlit/pages/home.py", title="홈", icon=":material/home:", default=True)
    notices_page = st.Page("test_streamlit/pages/notices.py", title="공지사항", icon=":material/notifications:")
    lms_page = st.Page("test_streamlit/pages/lms.py", title="LMS", icon=":material/school:")
    portal_page = st.Page("test_streamlit/pages/portal.py", title="포털", icon=":material/account_balance:")
    chatbot_page = st.Page("test_streamlit/pages/chatbot.py", title="AI 챗봇", icon=":material/smart_toy:")
    profile_page = st.Page("test_streamlit/pages/profile.py", title="프로필 / 설정", icon=":material/settings:")

    menu_pages = [home_page, notices_page]
    # LMS 페이지는 student_id가 확정됐을 때만(lms.py가 user["student_id"]를 직접 사용).
    if lms_linked() and get_student_id():
        menu_pages.append(lms_page)
    if portal_linked():
        menu_pages.append(portal_page)
    menu_pages.append(chatbot_page)

    pg = st.navigation({
        "메뉴": menu_pages,
        "계정": [profile_page],
    })
    pg.run()


if __name__ == "__main__":
    main()
