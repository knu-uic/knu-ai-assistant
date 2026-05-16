"""공지사항 페이지. 카테고리 필터 + 검색 + 내 학과/전체 토글."""

from datetime import date

import streamlit as st

from db import get_documents, search_chunks
from embed import embed_query
from ui import (
    CATEGORIES,
    CATEGORY_ICON,
    get_current_user,
    is_expired,
    row_to_notice_list,
    row_to_notice_search,
)

user = get_current_user()
major = user.get("major")

st.title("공지사항")
st.caption("교내 포털에서 자동 수집된 공지를 카테고리별로 정리했어요.")

# ── 필터 컨트롤 ────────────────────────────────────────────────
c_search, c_scope = st.columns([4, 1])
with c_search:
    search_query = st.text_input(
        "검색",
        placeholder="제목·내용·키워드로 검색…",
        label_visibility="collapsed",
    )
with c_scope:
    scope = st.segmented_control(
        "범위",
        ["내 학과", "전체"],
        default="내 학과",
        label_visibility="collapsed",
    ) or "내 학과"

selected_category = st.pills(
    "카테고리",
    CATEGORIES,
    default="전체",
    label_visibility="collapsed",
) or "전체"

show_expired = st.toggle("마감된 공지 표시", value=False)

# ── 조회 ───────────────────────────────────────────────────────
major_filter = major if scope == "내 학과" and major else None
notices: list[dict] = []

try:
    if search_query:
        q_vec = embed_query(search_query)
        cats = None if selected_category == "전체" else [selected_category]
        raw = search_chunks(
            q_vec, major=major_filter, categories=cats, kind="notice", limit=30,
        )
        notices = [row_to_notice_search(r) for r in (raw or [])]
    else:
        raw = get_documents(
            category=None if selected_category == "전체" else selected_category,
            major=major_filter,
            kind="notice",
        )
        notices = [row_to_notice_list(r) for r in (raw or [])]
except Exception as e:
    st.error(f"검색 실패: {e}")

today = date.today()
total_count = len(notices)
if not show_expired:
    notices = [n for n in notices if not is_expired(n, today)]
expired_hidden = total_count - len(notices)

if expired_hidden > 0:
    st.caption(f"🙈 마감된 공지 {expired_hidden}건 숨김 — 토글을 켜면 함께 표시됩니다.")

scope_label = f"{major} 맞춤" if major_filter else "전체"
st.caption(f"{len(notices)}건 · {scope_label}")

if not notices:
    st.info("표시할 공지사항이 없어요. 데이터를 수집하려면 `main.py`를 먼저 실행하세요.")

# ── 카드 리스트 ────────────────────────────────────────────────
for n in notices:
    expired = is_expired(n, today)
    cat = n.get("category") or ""
    icon = CATEGORY_ICON.get(cat, "📌")
    with st.container(border=True):
        left, right = st.columns([5, 1])
        with left:
            title_md = f"**[{n['title']}]({n['url']})**"
            if expired:
                title_md = f"🔒 ~~{title_md}~~"
            st.markdown(title_md)
        with right:
            st.caption(f"{icon} {cat}")

        meta = st.columns(4)
        posted_at = n.get("posted_at")
        if posted_at:
            meta[0].caption(f"🗓️ 등록: {posted_at}")

        target_list = n.get("target") or []
        if isinstance(target_list, str):
            target_list = [target_list]
        if target_list:
            meta[1].caption(f"👥 {', '.join(target_list)}")

        end_date = n.get("end_date")
        if end_date:
            deadline_label = "마감됨" if expired else "마감"
            meta[2].caption(f"📅 {deadline_label}: {end_date}")

        keywords = n.get("keywords") or []
        if isinstance(keywords, str):
            keywords = [keywords]
        if keywords:
            meta[3].caption(" ".join(f"#{k}" for k in keywords))

        score = n.get("score")
        if score is not None:
            st.caption(f"🔍 유사도: {score:.3f}")
