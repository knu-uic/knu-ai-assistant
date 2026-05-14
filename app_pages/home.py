"""홈 페이지. 관심사·학과 기반 추천 3건 + 마감 임박 공지."""

from datetime import date

import streamlit as st

from db import get_documents
from ui import (
    CATEGORY_ICON,
    get_current_user,
    is_expired,
    row_to_notice_list,
)


def _score_notice(notice: dict, interests: list[str], major: str | None, today: date) -> tuple[int, list[str]]:
    """관심키워드 매칭 + 학과 일치 + 마감 임박도로 점수 산출.

    임베딩 호출 없이 결정적으로 동작. 반환: (score, matched_keywords)
    """
    score = 0

    haystack_parts = [notice.get("title") or "", notice.get("content") or ""]
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

    if major:
        target = notice.get("target") or []
        if isinstance(target, str):
            target = [target]
        if notice.get("source_department") == major:
            score += 5
        if major in target:
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

        body = (notice.get("content") or "").strip().replace("\n", " ")
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
        end = notice.get("end_date")
        c[1].caption(f"{source} · 마감 {end}" if end else source)
        c[2].caption(f"{icon} {cat}")


# ─────────────────────────────────────────────────────────────

user = get_current_user()
today = date.today()
interests = user.get("interests") or []
major = user.get("major")

st.caption(today.strftime("%Y년 %-m월 %-d일"))
st.title(f"{user.get('name', '학생')}님, 오늘 꼭 필요한 3가지예요")

interest_label = ", ".join(f"'{kw}'" for kw in interests[:3]) if interests else "(없음)"
st.caption(
    f"{major or '학과 미설정'} · {user.get('year') or '-'}학년 기준으로 큐레이션했어요. "
    f"관심사 {interest_label} 반영됨."
)

# ── 추천 3건 ───────────────────────────────────────────────────
try:
    # 후보를 넉넉히(전 카테고리 60건) 가져와 점수 매김.
    raw = get_documents(major=major if major else None, limit=60)
except Exception as e:
    st.error(f"공지 조회 실패: {e}")
    raw = []

candidates = [row_to_notice_list(r) for r in (raw or [])]
candidates = [n for n in candidates if not is_expired(n, today)]

scored = []
for n in candidates:
    s, matched = _score_notice(n, interests, major, today)
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
