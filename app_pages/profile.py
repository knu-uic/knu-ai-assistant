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
            student_id=user["student_id"],
            name=new_name.strip() or "이름 미설정",
            major=new_major,
            year=int(new_year),
            interests=selected,
        )
        st.success("프로필이 저장됐어요.")
        st.rerun()
with c2:
    st.caption("저장하면 홈·공지·챗봇 페이지의 큐레이션·필터가 즉시 갱신됩니다.")

# ── 취득학점 현황 ───────────────────────────────────────────────
st.markdown("---")
st.subheader("🎓 취득학점 현황")

credits = user.get("graduation_credits")
if credits:
    import pandas as pd
    
    data = []
    
    def add_row(category, subcat, detail, ref_dict):
        try:
            if detail:
                standard = ref_dict.get(category, {}).get(subcat, {}).get(detail, {}).get("기준", "0")
                taken = ref_dict.get(category, {}).get(subcat, {}).get(detail, {}).get("취득", "0")
            elif subcat:
                standard = ref_dict.get(category, {}).get(subcat, {}).get("기준", "0")
                taken = ref_dict.get(category, {}).get(subcat, {}).get("취득", "0")
            else:
                standard = ref_dict.get(category, {}).get("기준", "0")
                taken = ref_dict.get(category, {}).get("취득", "0")
        except Exception:
            standard, taken = "0", "0"
            
        # 부족학점 계산
        try:
            std_val = float(standard) if "~" not in str(standard) else 0
            taken_val = float(taken)
            diff = max(0.0, std_val - taken_val)
            diff_str = f"{int(diff)}" if diff.is_integer() else f"{diff:.1f}"
            if std_val == 0 or "~" in str(standard):
                diff_str = "-"
        except Exception:
            diff_str = "-"
            
        cat_label = f"{category}"
        if subcat:
            cat_label += f" > {subcat}"
        if detail:
            cat_label += f" ({detail})"
            
        data.append({
            "영역 구분": cat_label,
            "기준 학점": standard,
            "취득 학점": taken,
            "부족 학점": diff_str
        })
        
    # 교양
    add_row("교양", "기초교양", "필수", credits)
    add_row("교양", "기초교양", "선택", credits)
    add_row("교양", "균형교양", "선택", credits)
    add_row("교양", "소양교양", "필수", credits)
    add_row("교양", "소양교양", "선택", credits)
    add_row("교양", "계", None, credits)
    
    # 전공
    add_row("전공", "최소전공인정학점", "전공기초", credits)
    add_row("전공", "최소전공인정학점", "콜라주", credits)
    add_row("전공", "최소전공인정학점", "전공핵심", credits)
    add_row("전공", "최소전공인정학점", "소계", credits)
    add_row("전공", "전공심화", None, credits)
    add_row("전공", "계", None, credits)
    
    # 교직
    add_row("교직", "자과", None, credits)
    add_row("교직", "타과", None, credits)
    
    # 기타
    add_row("융합탐색", None, None, credits)
    add_row("복수전공", "필수", None, credits)
    add_row("복수전공", "선택", None, credits)
    add_row("부전공", "필수", None, credits)
    add_row("부전공", "선택", None, credits)
    
    # 졸업학점계
    add_row("졸업학점계", None, None, credits)
    
    df = pd.DataFrame(data)
    
    # 테이블 스타일로 렌더링
    st.table(df)
else:
    st.info("통합정보시스템(포털) 졸업 학점 정보가 아직 연동되지 않았습니다. 로그아웃 후 다시 로그인해 주세요.")
