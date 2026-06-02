"""페이지 공용 상수, 데이터 변환 헬퍼, 사용자 컨텍스트."""

import html
from datetime import date

import streamlit as st

from db import get_user


# ── 도메인 상수 ─────────────────────────────────────────────────

CATEGORIES = ["전체", "장학", "수강", "취업(진로)", "행사(공모전)", "일반(기타)"]

CATEGORY_ICON = {
    "장학": "💰",
    "수강": "📚",
    "취업(진로)": "💼",
    "행사(공모전)": "🏆",
    "일반(기타)": "📌",
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


# ── 사용자 컨텍스트 ─────────────────────────────────────────────
# 신원(학번)은 세션/연동 상태에서 가져오며, 없으면 익명으로 동작한다.

CURRENT_STUDENT_ID_KEY = "current_student_id"


_ANON_PROFILE = {
    "student_id": None,
    "name": None,
    "major": None,
    "year": None,
    "interests": [],
}


def get_current_user() -> dict:
    """현재 사용자 프로필. 신원(학번)이 없으면 익명 빈 프로필을 반환(가짜 시드 안 함).

    신원 판별은 integrations.get_student_id()에 위임(지연 import로 순환 방지).
    """
    from integrations import get_student_id

    student_id = get_student_id()
    if not student_id:
        anon = dict(_ANON_PROFILE)
        anon["interests"] = st.session_state.get("interests", [])
        return anon

    user = get_user(student_id)
    if user is None:
        return {**_ANON_PROFILE, "student_id": student_id, "interests": st.session_state.get("interests", [])}
    return user


# ── DB row → notice dict ───────────────────────────────────────

def row_to_notice_search(row):
    """search_chunks 결과 row → notice dict."""

    (
        url,
        title,
        snippet,
        score,
        posted_at,
        start_date,
        end_date,
        category,
        target,
        keywords,
        source_code,
        source_name,
        _source_kind,
        source_department,
        *rest,
    ) = row

    summary = rest[0] if len(rest) > 0 else None
    body_content = rest[1] if len(rest) > 1 else None
    attachment_names = rest[2] if len(rest) > 2 else []
    chunk_type = rest[3] if len(rest) > 3 else None
    attachment_name = rest[4] if len(rest) > 4 else None

    return {
        "url": url,
        "title": title,
        "content": snippet,
        "body_content": body_content,
        "score": score,
        "summary": summary,
        "posted_at": posted_at,
        "start_date": start_date,
        "end_date": end_date,
        "category": category,
        "target": target,
        "keywords": keywords,
        "source_code": source_code,
        "source_name": source_name,
        "source_department": source_department,
        "attachment_names": attachment_names,
        "chunk_type": chunk_type,
        "attachment_name": attachment_name,
    }


def row_to_notice_list(row):
    """get_documents 결과 row → notice dict."""

    (
        url,
        title,
        content,
        posted_at,
        start_date,
        end_date,
        category,
        target,
        keywords,
        source_code,
        source_name,
        _source_kind,
        source_department,
        *rest,
    ) = row

    summary = rest[0] if len(rest) > 0 else None
    body_content = rest[1] if len(rest) > 1 else content
    attachment_names = rest[2] if len(rest) > 2 else []

    return {
        "url": url,
        "title": title,
        "content": content,
        "body_content": body_content,
        "score": None,
        "summary": summary,
        "posted_at": posted_at,
        "start_date": start_date,
        "end_date": end_date,
        "category": category,
        "target": target,
        "keywords": keywords,
        "source_code": source_code,
        "source_name": source_name,
        "source_department": source_department,
        "attachment_names": attachment_names,
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


# ── 포털 성적 그리드 렌더 ────────────────────────────────────────
# knuis_sync.py가 저장하는 그리드는 {title, columns: [...], rows: [[...]]} 구조.
# pandas 의존을 피하려 가로 스크롤 HTML 표로 렌더(시간표/취득학점 렌더와 동일 방식).

_GRADE_GRID_CSS = """
<style>
.grade-grid-container {
    margin: 6px 0 14px 0;
    border: 1px solid rgba(128, 128, 128, 0.15);
    border-radius: 8px;
    overflow-x: auto;
}
.grade-grid {
    width: 100%;
    border-collapse: collapse;
    text-align: center;
    font-size: 13px;
    white-space: nowrap;
}
.grade-grid th {
    background-color: rgba(128, 128, 128, 0.12);
    color: inherit;
    font-weight: 600;
    padding: 8px 10px;
    border: 1px solid rgba(128, 128, 128, 0.25);
}
.grade-grid td {
    padding: 8px 10px;
    border: 1px solid rgba(128, 128, 128, 0.15);
}
.grade-grid tbody tr:hover {
    background-color: rgba(128, 128, 128, 0.04);
}
</style>
"""


def _esc(value) -> str:
    return html.escape(str(value if value is not None else ""))


def render_grade_grid(grid: dict):
    """{title, columns, rows} 그리드를 가로 스크롤 HTML 표로 렌더. 빈 그리드는 무시."""
    if not grid or not grid.get("rows"):
        return
    columns = grid.get("columns") or []
    rows = grid.get("rows") or []
    title = grid.get("title")
    if title:
        st.markdown(f"**{_esc(title)}**")

    width = len(columns) if columns else (len(rows[0]) if rows else 0)
    parts = ['<div class="grade-grid-container"><table class="grade-grid">']
    if columns:
        parts.append(
            "<thead><tr>"
            + "".join(f"<th>{_esc(c)}</th>" for c in columns)
            + "</tr></thead>"
        )
    parts.append("<tbody>")
    for row in rows:
        cells = (list(row) + [""] * width)[:width] if width else list(row)
        parts.append(
            "<tr>" + "".join(f"<td>{_esc(c)}</td>" for c in cells) + "</tr>"
        )
    parts.append("</tbody></table></div>")
    st.markdown(_GRADE_GRID_CSS + "".join(parts), unsafe_allow_html=True)


def render_kv_summary(pairs):
    """[[라벨, 값], ...] 요약을 metric 카드 행으로 렌더."""
    pairs = [p for p in (pairs or []) if p and len(p) >= 2]
    if not pairs:
        return
    cols = st.columns(len(pairs))
    for col, pair in zip(cols, pairs):
        col.metric(str(pair[0]), str(pair[1]))
