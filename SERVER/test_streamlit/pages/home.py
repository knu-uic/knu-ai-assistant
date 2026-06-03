"""서버 테스트용 홈 페이지. 관심사·학과 기반 추천 3건 + 마감 임박 공지."""

from datetime import date

import streamlit as st

from db import get_documents
from test_streamlit.ui import (
    CATEGORY_ICON,
    get_current_user,
    is_expired,
    row_to_notice_list,
)


def _score_notice(
    notice: dict,
    interests: list[str],
    major: str | None,
    year: int | None,
    today: date,
) -> tuple[int, list[str]]:
    """관심키워드 매칭 + 학과 일치 + 마감 임박도로 점수 산출.

    임베딩 호출 없이 결정적으로 동작. 반환: (score, matched_keywords)
    """
    score = 0

    haystack_parts = [
        notice.get("title") or "",
        notice.get("body_content")
        or notice.get("summary")
        or notice.get("content")
        or "",
    ]
    notice_kws = notice.get("keywords") or []
    if isinstance(notice_kws, str):
        notice_kws = [notice_kws]
    haystack = " ".join(haystack_parts).lower()

    matched: list[str] = []
    for kw in interests:
        if not kw:
            continue
        if kw in notice_kws or kw.lower() in haystack:
            matched.append(kw)
    score += len(matched) * 10

    target = notice.get("target") or []
    if isinstance(target, str):
        target = [target]

    if major and notice.get("source_department") == major:
        score += 5

    if year and f"{year}학년" in target:
        score += 3
    if "전체" in target:
        score += 1

    end_date = notice.get("end_date")
    if end_date:
        days_left = (end_date - today).days
        if 0 <= days_left <= 14:
            # 가까울수록 부스트. (14→0, 0→5)
            score += max(0, 5 - days_left // 3)

    return score, matched


def _d_label(end_date, today: date) -> str:
    if not end_date:
        return ""
    delta = (end_date - today).days
    if delta == 0:
        return "D-DAY"
    if delta > 0:
        return f"D-{delta}"
    return f"D+{-delta}"


def _render_recommendation_card(rank: int, notice: dict, matched: list[str], today: date):
    cat = notice.get("category") or ""
    icon = CATEGORY_ICON.get(cat, "📌")
    d_lbl = _d_label(notice.get("end_date"), today)

    with st.container(border=True):
        top = st.columns([1, 1])
        top[0].caption(f"{icon} 추천 #{rank}")
        if d_lbl:
            top[1].markdown(
                f"<div style='text-align:right;color:#6366f1;font-weight:600'>{d_lbl}</div>",
                unsafe_allow_html=True,
            )

        st.markdown(f"**[{notice['title']}]({notice['url']})**")

        body = (
            notice.get("summary")
            or notice.get("body_content")
            or notice.get("content")
            or ""
        ).strip().replace("\n", " ")
        if len(body) > 120:
            body = body[:120] + "…"
        if body:
            st.caption(body)

        tags = []
        if cat:
            tags.append(f"● {cat}")
        for kw in matched[:2]:
            tags.append(f"✦ 관심키워드 '{kw}' 일치")
        if tags:
            st.caption("  ·  ".join(tags))


def _render_deadline_row(notice: dict, today: date):
    cat = notice.get("category") or ""
    icon = CATEGORY_ICON.get(cat, "📌")
    d_lbl = _d_label(notice.get("end_date"), today)

    with st.container(border=True):
        c = st.columns([1, 6, 2])
        c[0].markdown(f"**{d_lbl}**")
        c[1].markdown(f"[{notice['title']}]({notice['url']})")
        source = notice.get("source_name") or ""
        attachment_names = notice.get("attachment_names") or []
        end = notice.get("end_date")
        meta = f"{source} · 마감 {end}" if end else source

        if attachment_names:
            meta += f" · 첨부 {len(attachment_names)}개"

        c[1].caption(meta)
        c[2].caption(f"{icon} {cat}")


# ─────────────────────────────────────────────────────────────

user = get_current_user()
today = date.today()
interests = user.get("interests") or []
major = user.get("major")
year = user.get("year")

st.caption(today.strftime("%Y년 %-m월 %-d일"))
name = user.get("name")
if name:
    st.title(f"{name}님, 오늘 꼭 필요한 3가지예요")
else:
    st.title("오늘 꼭 필요한 3가지예요")

st.caption("관심사를 기준으로 큐레이션한 추천 공지입니다.")

# ── 추천 3건 ───────────────────────────────────────────────────
try:
    # 후보를 넉넉히(전 카테고리 60건) 가져와 점수 매김.
    raw = get_documents(major=major if major else None, limit=60)
except Exception as e:
    st.error(f"공지 조회 실패: {e}")
    raw = []

candidates = [row_to_notice_list(r) for r in (raw or [])]
_HIDDEN_SOURCE_CODES = {"cse_curriculum", "business_curriculum", "scholarship_info"}
candidates = [n for n in candidates if n.get("source_code") not in _HIDDEN_SOURCE_CODES]
candidates = [n for n in candidates if not is_expired(n, today)]

scored = []
for n in candidates:
    s, matched = _score_notice(n, interests, major, year, today)
    if s > 0:
        scored.append((s, n, matched))
scored.sort(key=lambda x: x[0], reverse=True)

top3 = scored[:3]
if not top3:
    st.info("아직 추천할 만한 공지가 충분히 모이지 않았어요. `main.py`로 데이터를 더 수집해 보세요.")
else:
    cols = st.columns(3)
    for col, (rank, (_score, notice, matched)) in zip(cols, enumerate(top3, start=1)):
        with col:
            _render_recommendation_card(rank, notice, matched, today)

st.write("")

# ── 마감 임박 ──────────────────────────────────────────────────
st.subheader("⏰ 마감 임박")
upcoming = [
    n for n in candidates
    if n.get("end_date") and 0 <= (n["end_date"] - today).days <= 30
]
upcoming.sort(key=lambda n: n["end_date"])
upcoming = upcoming[:5]

if not upcoming:
    st.caption("향후 30일 안에 마감되는 공지가 없어요.")
else:
    for n in upcoming:
        _render_deadline_row(n, today)

st.write("")

# ── 내 시간표 ──────────────────────────────────────────────────
st.subheader("📅 내 시간표")
timetable_list = user.get("timetable") or []
timetable_rows = None

# 요일/교시 정보가 들어있는 테이블 식별
for item in timetable_list:
    rows = item.get("rows") or []
    if rows and len(rows) > 1 and any("요일" in cell or "교시" in cell for cell in rows[0]):
        timetable_rows = rows
        break
        
if timetable_rows:
    try:
        import re
        header = timetable_rows[0]
        data = timetable_rows[1:]
        
        # 행별 열 개수 정합성 맞추기 및 간소화
        clean_data = []
        for r in data:
            if len(r) < len(header):
                r = r + [""] * (len(header) - len(r))
            elif len(r) > len(header):
                r = r[:len(header)]
            
            # 교시 이름 간단하게 정리 ("1교시 주간:(09:00~09:50)" -> "1교시")
            first_cell = r[0]
            if "교시" in first_cell:
                first_cell = first_cell.split(" ")[0]
            clean_row = [first_cell] + r[1:]
            clean_data.append(clean_row)
        
        # 수업이 하나도 없는 빈 교시 행은 제외하여 컴팩트하게 노출
        non_empty_rows = []
        for r in clean_data:
            has_class = any(r[i].strip() != "" for i in range(1, len(r)))
            if has_class:
                non_empty_rows.append(r)
                
        if non_empty_rows:
            # 토요일 컬럼에 수업이 전혀 없으면 토요일 컬럼 제외
            has_saturday_class = any(len(r) > 6 and r[6].strip() != "" for r in non_empty_rows)
            display_headers = list(header)
            if display_headers:
                display_headers[0] = "교시"
            if not has_saturday_class and "토요일" in display_headers:
                display_headers.remove("토요일")
                
            display_col_count = len(display_headers)
            
            def format_class_cell(cell_text: str) -> str:
                cell_text = cell_text.strip()
                if not cell_text:
                    return '<span class="empty-cell">-</span>'
                
                # 정규식 매칭: 과목명(분반 교수명) 강의실
                match = re.match(r"(.+)\((\d+)\s+([^)]+)\)\s*(.*)", cell_text)
                if match:
                    subject = match.group(1).strip()
                    div = match.group(2).strip()
                    prof = match.group(3).strip()
                    room = match.group(4).strip()
                    
                    room_html = f'<div style="font-size:11px; font-weight:600; margin-top:3px; color:#4338ca;">📍 {room}</div>' if room else ""
                    return (
                        f'<div class="class-cell">'
                        f'<div style="font-weight:600; font-size:12.5px; line-height:1.2;">{subject}</div>'
                        f'<div style="font-size:11px; opacity:0.75; margin-top:2px;">{prof} 교수 ({div}분반)</div>'
                        f'{room_html}'
                        f'</div>'
                    )
                return f'<div class="class-cell">{cell_text}</div>'

            html_lines = []
            html_lines.append("""
            <style>
            .timetable-container {
                margin-top: 10px;
                margin-bottom: 20px;
                border: 1px solid rgba(128, 128, 128, 0.15);
                border-radius: 8px;
                overflow-x: auto;
                background-color: transparent;
            }
            .timetable-table {
                width: 100%;
                border-collapse: collapse;
                text-align: center;
                font-size: 13px;
            }
            .timetable-table th {
                background-color: rgba(128, 128, 128, 0.12);
                color: inherit;
                font-weight: 600;
                padding: 10px 12px;
                border: 1px solid rgba(128, 128, 128, 0.25);
                font-size: 12.5px;
                vertical-align: middle;
                white-space: nowrap;
            }
            .timetable-table td {
                padding: 10px 12px;
                border: 1px solid rgba(128, 128, 128, 0.15);
                font-size: 13px;
                vertical-align: middle;
                white-space: normal;
            }
            .timetable-table tr:hover {
                background-color: rgba(128, 128, 128, 0.04);
            }
            .time-col {
                font-weight: bold;
                background-color: rgba(128, 128, 128, 0.06);
                text-align: center;
                font-size: 13px;
                width: 10%;
                white-space: nowrap;
            }
            .class-cell {
                background-color: rgba(99, 102, 241, 0.08);
                color: #3730a3;
                border: 1px solid rgba(99, 102, 241, 0.2);
                border-radius: 6px;
                padding: 8px 10px;
                text-align: center;
                white-space: normal;
                word-break: keep-all;
                max-width: 130px;
                margin: 0 auto;
            }
            .empty-cell {
                color: rgba(128, 128, 128, 0.35);
            }
            </style>
            <div class="timetable-container">
            <table class="timetable-table">
                <thead>
                    <tr>
            """)
            
            for h in display_headers:
                html_lines.append(f"<th>{h}</th>")
            html_lines.append("</tr></thead><tbody>")
            
            for r in non_empty_rows:
                html_lines.append("<tr>")
                html_lines.append(f"<td class='time-col'>{r[0]}</td>")
                for i in range(1, display_col_count):
                    cell_val = r[i] if i < len(r) else ""
                    html_lines.append(f"<td>{format_class_cell(cell_val)}</td>")
                html_lines.append("</tr>")
                
            html_lines.append("</tbody></table></div>")
            st.markdown("".join(html_lines), unsafe_allow_html=True)
        else:
            st.info("이번 학기 시간표에 등록된 수업이 없습니다.")
    except Exception as ex:
        st.error(f"시간표를 표시하는 중 오류가 발생했습니다: {ex}")
else:
    st.info("통합정보시스템(포털) 시간표가 아직 연동되지 않았습니다. 설정 페이지에서 포털을 연동하면 시간표가 표시됩니다.")
