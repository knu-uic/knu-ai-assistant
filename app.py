import streamlit as st
from dotenv import load_dotenv

from db import get_documents, search_chunks
from embed import embed_query
from graph import GRAPH

load_dotenv()

CATEGORIES = ["전체", "장학/등록", "학사/수업", "진로/취업", "행사/공모전", "일반/기타"]
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
    "장학/등록": "💰", "학사/수업": "📚",
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


def _row_to_notice_search(row):
    """search_chunks 결과 row → notice dict."""
    (url, title, snippet, score, start_date, end_date,
     category, target, keywords,
     _source_code, source_name, _source_kind, _source_department) = row
    return {
        "url": url, "title": title, "content": snippet, "score": score,
        "start_date": start_date, "end_date": end_date, "category": category,
        "target": target, "keywords": keywords,
        "source_name": source_name,
    }


def _row_to_notice_list(row):
    """get_documents 결과 row → notice dict."""
    (url, title, content, start_date, end_date,
     category, target, keywords,
     _source_code, source_name, _source_kind, _source_department) = row
    return {
        "url": url, "title": title, "content": content, "score": None,
        "start_date": start_date, "end_date": end_date, "category": category,
        "target": target, "keywords": keywords,
        "source_name": source_name,
    }


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
            q_vec = embed_query(search_query)
            cats = None if selected_category == "전체" else [selected_category]
            raw = search_chunks(
                q_vec,
                major=None if major == "전체" else major,
                categories=cats,
                limit=20,
            )
            notices = [_row_to_notice_search(r) for r in (raw or [])]
        else:
            raw = get_documents(
                category=None if selected_category == "전체" else selected_category,
                major=None if major == "전체" else major,
            )
            notices = [_row_to_notice_list(r) for r in (raw or [])]
    except Exception as e:
        st.error(f"검색 실패: {e}")

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

            end_date = n.get("end_date")
            if end_date:
                meta[1].caption(f"📅 마감: {end_date}")

            keywords = n.get("keywords") or []
            if isinstance(keywords, str):
                keywords = [keywords]
            if keywords:
                meta[2].caption(" ".join(f"#{k}" for k in keywords))

            score = n.get("score")
            if score is not None:
                st.caption(f"🔍 유사도: {score:.3f}")

# ── Tab 2: AI 챗봇 ────────────────────────────────────────────
with tab_chat:
    st.caption(f"현재 설정된 학과: **{major}** — 학과에 맞는 공지사항을 우선 검색합니다.")

    if "chat_history" not in st.session_state:
        st.session_state.chat_history = []

    for msg in st.session_state.chat_history:
        with st.chat_message(msg["role"]):
            st.markdown(msg["content"])

    user_input = st.chat_input("질문을 입력하세요 (예: 이번 학기 장학금 신청 일정 알려줘)")
    if user_input:
        st.session_state.chat_history.append({"role": "user", "content": user_input})
        with st.chat_message("user"):
            st.markdown(user_input)

        with st.chat_message("assistant"):
            try:
                result = GRAPH.invoke(
                    {
                        "question": user_input,
                        "major": None if major == "전체" else major,
                    },
                    config={
                        "metadata": {"major": major, "question": user_input},
                        "tags": ["streamlit-chat", f"major:{major}"],
                    },
                )
                answer = result.get("answer", "")
                st.markdown(answer)

                grounded = result.get("grounded")
                fidelity = result.get("fidelity")
                if grounded is not None:
                    badge = "✅ 근거 있음" if grounded else "⚠️ 할루시네이션 의심"
                    score_str = f" (충실도 {fidelity:.2f})" if fidelity is not None else ""
                    st.caption(f"{badge}{score_str} — {result.get('verifier_note', '')}")

                with st.expander("🔍 검색·라우팅 디버그"):
                    cats = result.get("categories") or []
                    st.caption(f"카테고리: **{', '.join(cats) if cats else '(없음)'}**")
                    st.caption(f"확장 쿼리: `{result.get('expanded_query', '')}`")
                    st.caption(f"라우터 사유: {result.get('route_rationale', '')}")
                    contexts = result.get("contexts") or []
                    if not contexts:
                        st.caption("(검색 결과 없음)")
                    for c in contexts:
                        st.markdown(
                            f"- [{c['title']}]({c['url']}) · 유사도 {c['score']:.3f}"
                        )

                st.session_state.chat_history.append({"role": "assistant", "content": answer})
            except Exception as e:
                err = f"답변 생성 실패: {e}"
                st.error(err)
                st.session_state.chat_history.append({"role": "assistant", "content": err})
