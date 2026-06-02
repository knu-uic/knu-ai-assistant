"""설정 페이지. 계정 연동(LMS·포털) + 학적(읽기전용) + 관심키워드 편집."""

import streamlit as st

from db import upsert_user
from integrations import (
    clear_links,
    get_student_id,
    lms_linked,
    login_lms,
    portal_linked,
    sync_portal,
)
from ui import (
    CURRENT_STUDENT_ID_KEY,
    INTEREST_KEYWORD_POOL,
    MAX_INTERESTS,
    get_current_user,
)

user = get_current_user()
sid = user.get("student_id")

st.title("프로필 / 설정")

# ── 계정 연동 ──────────────────────────────────────────────────
with st.container(border=True):
    st.subheader("🔗 계정 연동")
    lms_ok = lms_linked()
    portal_ok = portal_linked()

    badge = st.columns(2)
    badge[0].markdown(f"**LMS** {'✅ 연동됨' if lms_ok else '⚪ 미연동'}")
    badge[1].markdown(f"**포털** {'✅ 연동됨' if portal_ok else '⚪ 미연동'}")

    if lms_ok and portal_ok:
        st.caption("공주대 통합 계정으로 LMS·포털이 모두 연동되어 있어요.")
        if st.button("연동 해제", key="unlink_all"):
            clear_links()
            st.rerun()

    elif lms_ok and not portal_ok:
        # LMS만 연동된 상태 → 포털 재시도(비밀번호 재입력 필요).
        st.caption("LMS는 연동됐어요. 포털을 연동하면 시간표·취득학점·성적이 표시됩니다.")
        with st.form("portal_retry_form"):
            pw = st.text_input("비밀번호 (포털 연동 재시도)", type="password")
            retry = st.form_submit_button("포털 연동", type="primary")
        if retry:
            if not pw:
                st.warning("비밀번호를 입력해 주세요.")
            else:
                with st.spinner("포털 정보를 연동 중이에요(최대 수십 초)…"):
                    portal_res = sync_portal(get_student_id(), pw)
                if portal_res.returncode == 0:
                    st.toast("포털 연동 완료", icon="✅")
                    st.rerun()
                else:
                    st.error(portal_res.stderr.strip() or portal_res.stdout.strip() or "포털 연동에 실패했어요.")
        col_a, _ = st.columns([1, 4])
        if col_a.button("연동 해제", key="unlink_lms"):
            clear_links()
            st.rerun()

    else:
        # 둘 다 미연동 → 통합 계정 1회 로그인으로 LMS·포털 함께 연동.
        st.caption("공주대 통합 계정(LMS·포털 동일)으로 로그인하면 LMS·포털이 함께 연동됩니다. 비밀번호는 저장하지 않아요.")
        with st.form("link_form"):
            username = st.text_input("학번")
            password = st.text_input("비밀번호", type="password")
            submitted = st.form_submit_button("연동", type="primary")
        if submitted:
            if not username.strip() or not password:
                st.warning("학번과 비밀번호를 입력해 주세요.")
            else:
                # 1) LMS 먼저(빠름·신뢰) → 성공 시 신원 확정.
                with st.spinner("LMS 연동 중이에요…"):
                    lms_res = login_lms(username.strip(), password)
                if lms_res.returncode != 0:
                    st.error(lms_res.stderr.strip() or lms_res.stdout.strip() or "LMS 연동에 실패했어요.")
                else:
                    st.session_state[CURRENT_STUDENT_ID_KEY] = username.strip()
                    st.session_state.lms_startup_synced = False
                    st.toast("LMS 연동 완료", icon="✅")
                    # 2) 포털 독립 실행(느림). 실패해도 LMS는 유지.
                    with st.spinner("포털 정보를 연동 중이에요(최대 수십 초)…"):
                        portal_res = sync_portal(username.strip(), password)
                    if portal_res.returncode == 0:
                        st.toast("포털 연동 완료", icon="✅")
                    else:
                        st.toast("포털 연동 실패(LMS는 유지). 설정에서 재시도하세요.", icon="⚠️")
                    st.rerun()

# ── 학적 (연동 시에만 표시) ──────────────────────
if sid:
    with st.container(border=True):
        st.subheader(user.get("name") or "이름 미설정")
        cols = st.columns(3)
        cols[0].metric("학번", user.get("student_id") or "-")
        cols[1].metric("학과", user.get("major") or "-")
        cols[2].metric("학년", f"{user['year']}학년" if user.get("year") else "-")
else:
    st.info("계정을 연동하면 학적·성적 정보를 추가로 볼 수 있어요.")

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

# ── 저장 (관심키워드만 갱신, 학적은 보존) ──────────────────────
c1, c2 = st.columns([1, 5])
with c1:
    if st.button("저장", type="primary", use_container_width=True):
        if sid:
            # name/major/year는 ON CONFLICT 시 EXCLUDED로 덮어쓰므로 현재 값을 그대로 넘겨 보존.
            upsert_user(
                student_id=user["student_id"],
                name=user.get("name") or "이름 미설정",
                major=user.get("major") or "",
                year=user.get("year"),
                interests=selected,
            )
        else:
            st.session_state["interests"] = selected
        st.success("관심 키워드가 저장됐어요.")
        st.rerun()
with c2:
    st.caption("관심 키워드를 저장하면 홈·공지·챗봇의 큐레이션이 즉시 갱신됩니다.")
