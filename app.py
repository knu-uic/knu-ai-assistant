import streamlit as st
from dotenv import load_dotenv
from langchain_core.messages import SystemMessage, HumanMessage, AIMessage, BaseMessage
from model import get_model
from db import search_notice, get_notices

load_dotenv()

CATEGORIES = ["전체", "장학/등록", "학사/학적", "진로/취업", "행사/공모전", "일반/기타"]
MAJORS = [
    # 기존 항목
    "전체", "컴퓨터공학과", "소프트웨어학과", "전자공학과", "기계공학과",
    "화학공학과", "건축학과", "경영학과", "영어영문학과", "수학과", "물리학과",
    
    # 공주대학교 추가 항목 (본부소속)
    "인공지능학부", "국제학부", "교양학부", "자율전공학부",
    
    # 사범대학
    "국어교육과", "한문교육과", "영어교육과", "윤리교육과", "교육학과", 
    "경영·금융교육과", "문헌정보교육과", "특수교육과", "역사교육과", 
    "일반사회교육과", "지리교육과", "유아교육과", "수학교육과", "물리교육과", 
    "화학교육과", "생물교육과", "지구과학교육과", "환경교육과", "컴퓨터교육과", 
    "체육교육과", "음악교육과", "미술교육과", "기술·가정교육과",
    
    # 인문사회과학대학
    "중어중문학과", "불어불문학과", "독어독문학과", "사학과", "지리학과", 
    "경제통상학부", "관광경영학과", "관광&영어통역융복합학과", "행정학과", 
    "법학과", "사회복지학과",
    
    # 자연과학대학
    "데이터정보물리학과", "응용수학과", "화학과", "생명과학과", "지질환경과학과", 
    "대기과학과", "문화재보존과학과", "의류상품학과", "스포츠과학과",
    
    # 천안공과대학
    "신소재공학부", "그린스마트건축공학과", "미래자동차공학과", 
    "스마트인프라공학과", "화학공학부", "전기전자제어공학부", "디자인컨버전스학과", 
    "환경공학과", "지능형모빌리티공학과", "스마트정보기술공학과", "정보통신공학과", 
    "산업공학과", "기계자동차공학부", "디지털융합금형공학과", "광공학과", 
    "도시·교통공학과",
    
    # 산업과학대학
    "지역사회개발학과", "부동산학과", "산업유통학과", "식물자원학과", "원예학과", 
    "동물자원학과", "지역건설공학과", "스마트팜공학과", "산림과학과", "조경학과", 
    "식품영양학과", "외식상품학과", "식품공학과", "특수동물학과", "수산생명의학과",
    
    # 간호보건대학
    "보건행정학과", "의료정보학과", "응급구조학과", "간호학과",
    
    # 예술대학
    "만화애니메이션학부", "도자문화융합디자인학과", "무용학과", "가구리빙디자인학과", 
    "게임디자인학과", "주얼리·금속디자인학과", "영상학과"
]
CATEGORY_ICON = {
    "장학/등록": "💰", "학사/학적": "📚",
    "진로/취업": "💼", "행사/공모전": "🏆", "일반/기타": "📌",
}

st.set_page_config(page_title="KNU 지능형 학생 비서", page_icon="🎓", layout="wide")

# ── Sidebar: 사용자 프로필 ─────────────────────────────────────
with st.sidebar:
    st.title("내 프로필")
    major = st.selectbox("학과", MAJORS)
    st.divider()
    st.caption("KNU 지능형 학생 비서 v0.1 프로토타입")
    st.caption("학과를 설정하면 맞춤형 공지사항과 챗봇 답변을 받을 수 있습니다.")

# ── 헤더 ──────────────────────────────────────────────────────
st.title("KNU 지능형 학생 비서 🎓")
st.caption("공주대학교 학생을 위한 맞춤형 공지사항 검색 및 AI 상담 서비스")

tab_board, tab_chat = st.tabs(["📋 공지사항 게시판", "🤖 AI 챗봇"])

# ── Tab 1: 공지사항 게시판 ─────────────────────────────────────
with tab_board:
    col_search, col_cat = st.columns([3, 1])
    with col_search:
        search_query = st.text_input(
            "공지사항 검색",
            placeholder="예: 해외 교환학생, 장학금 신청, 캡스톤 설계...",
        )
    with col_cat:
        selected_category = st.selectbox("카테고리", CATEGORIES)

    notices = []
    is_search_mode = bool(search_query)

    try:
        if is_search_mode:
            raw = search_notice(search_query, major, limit=10)
            for title, category, target, url, score in (raw or []):
                notices.append({
                    "url": url, "title": title, "category": category,
                    "target": target, "score": score,
                })
            st.caption(f"'{search_query}' 의미 기반 검색 결과 **{len(notices)}건**")
        else:
            raw = get_notices(
                category=None if selected_category == "전체" else selected_category,
                major=None if major == "전체" else major,
            )
            for url, title, content, start_date, end_date, category, target, keywords in (raw or []):
                notices.append({
                    "url": url, "title": title, "content": content,
                    'start_date': start_date, 'end_date': end_date, "category": category,
                    "target": target, "keywords": keywords,
                })
    except Exception as e:
        st.error(f"데이터베이스 연결 실패: {e}")

    if not notices:
        st.info("표시할 공지사항이 없습니다. 데이터를 수집하려면 `main.py`를 먼저 실행하세요.")

    for n in notices:
        with st.container(border=True):
            left, right = st.columns([5, 1])
            cat = n.get("category") or ""
            with left:
                st.markdown(f"**[{n['title']}]({n['url']})**")
            with right:
                st.caption(f"{CATEGORY_ICON.get(cat, '📌')} {cat}")

            meta = st.columns(3)
            target_list = n.get("target") or []
            if isinstance(target_list, str):
                target_list = [target_list]
            if target_list:
                meta[0].caption(f"👥 {', '.join(target_list)}")

            deadline = n.get("deadline")
            if deadline:
                meta[1].caption(f"📅 마감: {deadline}")

            if is_search_mode:
                score = n.get("score", 0)
                meta[2].caption(f"🎯 유사도: {score:.0%}")
            else:
                keywords = n.get("keywords") or []
                if isinstance(keywords, str):
                    keywords = [keywords]
                if keywords:
                    meta[2].caption(" ".join(f"#{k}" for k in keywords))

def _rewrite_query_for_search(history: list[dict], current_prompt: str) -> str:
    """이전 대화를 참고해 마지막 질문을 단독 검색 가능한 질의로 재작성."""
    if not history:
        return current_prompt

    history_text = "\n".join(
        f"{'사용자' if m['role'] == 'user' else '어시스턴트'}: {m['content']}"
        for m in history
    )
    rewrite_prompt = f"""아래 대화를 참고해서, 마지막 사용자 질문을 검색 시스템에 전달할 수 있는 독립적인 한국어 질의로 다시 써라.
대명사("그거", "이건")나 생략된 주제를 명시적으로 풀어서 단독으로 의미가 통하게 만들어라.
다시 쓴 질의 한 줄만 출력하라. 다른 말은 절대 붙이지 말 것.

# 대화
{history_text}

# 다시 쓸 마지막 질문
{current_prompt}
"""
    response = get_model().invoke([HumanMessage(content=rewrite_prompt)])
    return str(response.content).strip() or current_prompt


# ── Tab 2: AI 챗봇 ────────────────────────────────────────────
with tab_chat:
    st.caption(f"현재 설정된 학과: **{major}** — 학과에 맞는 공지사항을 우선 검색합니다.")

    if "chat_history" not in st.session_state:
        st.session_state.chat_history = []

    for msg in st.session_state.chat_history:
        with st.chat_message(msg["role"]):
            st.markdown(msg["content"])

    if prompt := st.chat_input("궁금한 것을 물어보세요! (예: 이번 학기 장학금 신청 일정 알려줘)"):
        st.session_state.chat_history.append({"role": "user", "content": prompt})
        with st.chat_message("user"):
            st.markdown(prompt)

        with st.chat_message("assistant"):
            prior_history = st.session_state.chat_history[:-1]
            search_query = _rewrite_query_for_search(prior_history, prompt)

            context_lines = []
            try:
                results = search_notice(search_query, major, limit=5) or []
                for title, category, target, url, score in results:
                    context_lines.append(f"- [{title}]({url}) (카테고리: {category}, 유사도: {score:.0%})")
            except Exception:
                pass

            context = "\n".join(context_lines) if context_lines else "관련 공지사항을 찾지 못했습니다."

            system_prompt = f"""너는 공주대학교 학생을 위한 AI 학생 비서야.
학생 정보: 학과={major}

아래 관련 공지사항을 참고해서 답변해줘:
{context}

규칙:
- 없는 정보는 절대 지어내지 마.
- 공지사항 링크를 인용하며 답변해.
- 한국어로 간결하게 답변해."""

            messages: list[BaseMessage] = [SystemMessage(content=system_prompt)]
            for m in prior_history:
                if m["role"] == "user":
                    messages.append(HumanMessage(content=m["content"]))
                elif m["role"] == "assistant":
                    messages.append(AIMessage(content=m["content"]))
            messages.append(HumanMessage(content=prompt))

            with st.spinner("답변 생성 중..."):
                response = get_model().invoke(messages)
            answer = response.content
            st.markdown(answer)

            if context_lines:
                with st.expander("참고한 공지사항 보기"):
                    if search_query != prompt:
                        st.caption(f"🔁 검색용으로 재작성된 질의: `{search_query}`")
                    st.markdown(context)

        st.session_state.chat_history.append({"role": "assistant", "content": answer})
