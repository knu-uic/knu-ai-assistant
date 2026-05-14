"""프로필 / 설정 페이지. 이름·학과·학년·관심키워드 편집."""

import streamlit as st

from db import upsert_user
from ui import (
    DEFAULT_STUDENT_ID,
    INTEREST_KEYWORD_POOL,
    MAJORS,
    MAX_INTERESTS,
    get_current_user,
)

user = get_current_user()

st.title("프로필 / 설정")
st.caption("학과·학년·관심사를 기반으로 공지사항이 큐레이션돼요.")

# ── 기본 정보 ──────────────────────────────────────────────────
with st.container(border=True):
    st.subheader(user.get("name") or "이름 미설정")
    st.caption(f"학번 {user['student_id']}")

    cols = st.columns(3)
    major_options = [m for m in MAJORS if m != "전체"]
    default_major_idx = (
        major_options.index(user["major"]) if user.get("major") in major_options else 0
    )
    new_major = cols[0].selectbox("소속 학과", major_options, index=default_major_idx)
    new_year = cols[1].number_input(
        "학년", min_value=1, max_value=6, step=1, value=user.get("year") or 1
    )
    new_name = cols[2].text_input("이름", value=user.get("name") or "")

# ── 관심 키워드 ────────────────────────────────────────────────
with st.container(border=True):
    st.subheader("관심 키워드")
    st.caption(f"선택한 키워드가 포함된 공지가 우선 큐레이션돼요. (최대 {MAX_INTERESTS}개)")

    selected = st.pills(
        "관심 키워드",
        options=INTEREST_KEYWORD_POOL,
        selection_mode="multi",
        default=user.get("interests") or [],
        label_visibility="collapsed",
    ) or []

    if len(selected) > MAX_INTERESTS:
        st.warning(f"최대 {MAX_INTERESTS}개까지 선택할 수 있어요. 앞에서 {MAX_INTERESTS}개만 저장됩니다.")
        selected = selected[:MAX_INTERESTS]

# ── 저장 ───────────────────────────────────────────────────────
c1, c2 = st.columns([1, 5])
with c1:
    if st.button("저장", type="primary", use_container_width=True):
        upsert_user(
            student_id=DEFAULT_STUDENT_ID,
            name=new_name.strip() or "이름 미설정",
            major=new_major,
            year=int(new_year),
            interests=selected,
        )
        st.success("프로필이 저장됐어요.")
        st.rerun()
with c2:
    st.caption("저장하면 홈·공지·챗봇 페이지의 큐레이션·필터가 즉시 갱신됩니다.")
