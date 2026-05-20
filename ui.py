"""페이지 공용 상수, 데이터 변환 헬퍼, 사용자 컨텍스트."""

from datetime import date

import streamlit as st

from db import get_user, upsert_user


# ── 도메인 상수 ─────────────────────────────────────────────────

CATEGORIES = ["전체", "장학/등록", "학사/수업", "진로/취업", "행사/공모전", "일반/기타"]

CATEGORY_ICON = {
    "장학/등록": "💰",
    "학사/수업": "📚",
    "진로/취업": "💼",
    "행사/공모전": "🏆",
    "일반/기타": "📌",
}

MAJORS = [
    "전체", "컴퓨터공학과", "소프트웨어학과", "전자공학과", "기계공학과",
    "화학공학과", "건축학과", "경영학과", "영어영문학과", "수학과", "물리학과",
    "인공지능학부", "국제학부", "교양학부", "자율전공학부",
    "국어교육과", "한문교육과", "영어교육과", "윤리교육과", "교육학과",
    "경영·금융교육과", "문헌정보교육과", "특수교육과", "역사교육과",
    "일반사회교육과", "지리교육과", "유아교육과", "수학교육과", "물리교육과",
    "화학교육과", "생물교육과", "지구과학교육과", "환경교육과", "컴퓨터교육과",
    "체육교육과", "음악교육과", "미술교육과", "기술·가정교육과",
    "중어중문학과", "불어불문학과", "독어독문학과", "사학과", "지리학과",
    "경제통상학부", "관광경영학과", "관광&영어통역융복합학과", "행정학과",
    "법학과", "사회복지학과",
    "데이터정보물리학과", "응용수학과", "화학과", "생명과학과", "지질환경과학과",
    "대기과학과", "문화재보존과학과", "의류상품학과", "스포츠과학과",
    "신소재공학부", "그린스마트건축공학과", "미래자동차공학과",
    "스마트인프라공학과", "화학공학부", "전기전자제어공학부", "디자인컨버전스학과",
    "환경공학과", "지능형모빌리티공학과", "스마트정보기술공학과", "정보통신공학과",
    "산업공학과", "기계자동차공학부", "디지털융합금형공학과", "광공학과",
    "도시·교통공학과",
    "지역사회개발학과", "부동산학과", "산업유통학과", "식물자원학과", "원예학과",
    "동물자원학과", "지역건설공학과", "스마트팜공학과", "산림과학과", "조경학과",
    "식품영양학과", "외식상품학과", "식품공학과", "특수동물학과", "수산생명의학과",
    "보건행정학과", "의료정보학과", "응급구조학과", "간호학과",
    "만화애니메이션학부", "도자문화융합디자인학과", "무용학과", "가구리빙디자인학과",
    "게임디자인학과", "주얼리·금속디자인학과", "영상학과",
]

# 프로필 페이지의 관심키워드 풀. 스크린샷의 칩 라벨을 기반으로 한다.
INTEREST_KEYWORD_POOL = [
    "인턴", "장학금", "캡스톤", "해커톤", "교환학생", "공모전",
    "근로장학", "특강", "동아리", "취업박람회",
]

MAX_INTERESTS = 6


# ── 단일 사용자 컨텍스트 ────────────────────────────────────────
# 프로토타입은 한 명만 쓴다고 가정. 학번 키만 정의하고 첫 진입 시 시드한다.

DEFAULT_STUDENT_ID = "202112345"
_DEFAULT_PROFILE = {
    "student_id": DEFAULT_STUDENT_ID,
    "name": "이지원",
    "major": "컴퓨터공학과",
    "year": 3,
    "interests": ["인턴", "장학금", "캡스톤", "해커톤"],
}


def get_current_user() -> dict:
    """현재 사용자 프로필. DB에 없으면 기본값으로 시드한 뒤 반환."""
    user = get_user(DEFAULT_STUDENT_ID)
    if user is None:
        upsert_user(
            student_id=_DEFAULT_PROFILE["student_id"],
            name=_DEFAULT_PROFILE["name"],
            major=_DEFAULT_PROFILE["major"],
            year=_DEFAULT_PROFILE["year"],
            interests=_DEFAULT_PROFILE["interests"],
        )
        user = get_user(DEFAULT_STUDENT_ID)
    assert user is not None
    return user


# ── DB row → notice dict ───────────────────────────────────────

def row_to_notice_search(row):
    """search_chunks 결과 row → notice dict."""
    (url, title, snippet, score, posted_at, start_date, end_date,
     category, target, keywords,
     _source_code, source_name, _source_kind, source_department, *rest) = row
    summary = rest[0] if rest else None
    return {
        "url": url, "title": title, "content": snippet, "score": score,
        "summary": summary,
        "posted_at": posted_at,
        "start_date": start_date, "end_date": end_date, "category": category,
        "target": target, "keywords": keywords,
        "source_name": source_name, "source_department": source_department,
    }


def row_to_notice_list(row):
    """get_documents 결과 row → notice dict."""
    (url, title, content, posted_at, start_date, end_date,
     category, target, keywords,
     _source_code, source_name, _source_kind, source_department, *rest) = row
    summary = rest[0] if rest else None
    return {
        "url": url, "title": title, "content": content, "score": None,
        "summary": summary,
        "posted_at": posted_at,
        "start_date": start_date, "end_date": end_date, "category": category,
        "target": target, "keywords": keywords,
        "source_name": source_name, "source_department": source_department,
    }


def is_expired(notice: dict, today: date) -> bool:
    ed = notice.get("end_date")
    return ed is not None and ed < today


# ── 사이드바 프로필 카드 ────────────────────────────────────────

def render_sidebar_user_card(user: dict):
    initial = (user.get("name") or "?")[:1]
    with st.sidebar:
        st.markdown("---")
        c1, c2 = st.columns([1, 4])
        with c1:
            st.markdown(
                f"<div style='width:36px;height:36px;border-radius:50%;"
                f"background:#e0e7ff;color:#3730a3;display:flex;align-items:center;"
                f"justify-content:center;font-weight:700;'>{initial}</div>",
                unsafe_allow_html=True,
            )
        with c2:
            st.markdown(f"**{user.get('name') or '이름 미설정'}**")
            year_str = f"· {user['year']}학년" if user.get("year") else ""
            st.caption(f"{user.get('major') or '학과 미설정'} {year_str}")
