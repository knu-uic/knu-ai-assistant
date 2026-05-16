"""KNU 지능형 학생 비서 진입점. st.navigation으로 4페이지 라우팅."""

import threading

import streamlit as st
from dotenv import load_dotenv

from db import ensure_users_schema
from rerank import _get_reranker
from ui import get_current_user, render_sidebar_user_card

load_dotenv()

st.set_page_config(page_title="KNU 학생 비서", page_icon="🎓", layout="wide")


# 첫 챗봇 질문 응답이 느린 원인: rerank.py의 BGE-reranker가 lazy 패턴이라
# 첫 호출(=첫 질문) 시 메모리 로드. streamlit 부팅 직후 daemon thread로 미리 올려둠.
# cache_resource로 모든 rerun/세션 사이 1회만 실행 보장.
@st.cache_resource(show_spinner=False)
def _warmup_reranker():
    t = threading.Thread(target=_get_reranker, daemon=True, name="reranker-warmup")
    t.start()
    return t


_warmup_reranker()

# DB에 users 테이블/year 컬럼이 없는 환경(이미 init_db된 구버전 DB)도 흡수.
# 세션 내 한 번만 실행.
if "_schema_ensured" not in st.session_state:
    ensure_users_schema()
    st.session_state._schema_ensured = True

# 사이드바 상단 브랜딩.
with st.sidebar:
    st.markdown("### 🎓 KNU 학생 비서")
    st.caption("공주대학교")

# 사이드바 하단 사용자 카드. 페이지 본문 이전에 그려둔다.
user = get_current_user()
render_sidebar_user_card(user)

home_page = st.Page("app_pages/home.py", title="홈", icon=":material/home:", default=True)
notices_page = st.Page("app_pages/notices.py", title="공지사항", icon=":material/notifications:")
chatbot_page = st.Page("app_pages/chatbot.py", title="AI 챗봇", icon=":material/smart_toy:")
profile_page = st.Page("app_pages/profile.py", title="프로필 / 설정", icon=":material/settings:")

pg = st.navigation({
    "메뉴": [home_page, notices_page, chatbot_page],
    "계정": [profile_page],
})
pg.run()
