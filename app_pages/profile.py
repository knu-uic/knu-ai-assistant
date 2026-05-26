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

credits = user.get("graduation_credits")
if credits:
    st.subheader("🎓 취득학점 현황")
    st.caption("통합정보시스템(KNUIS)에서 동기화된 졸업사전예고 취득학점 상세 현황입니다. (가로 스크롤 가능)")
    
    html_lines = []
    html_lines.append("""
    <style>
    .grad-container {
        margin-top: 10px;
        border: 1px solid rgba(128, 128, 128, 0.15);
        border-radius: 8px;
        overflow-x: auto;
        background-color: transparent;
    }
    .grad-table {
        width: 100%;
        border-collapse: collapse;
        text-align: center;
        font-size: 13px;
        white-space: nowrap;
    }
    .grad-table th {
        background-color: rgba(128, 128, 128, 0.12);
        color: inherit;
        font-weight: 600;
        padding: 8px 10px;
        border: 1px solid rgba(128, 128, 128, 0.25);
        font-size: 12.5px;
        vertical-align: middle;
    }
    .grad-table td {
        padding: 10px 12px;
        border: 1px solid rgba(128, 128, 128, 0.15);
        font-size: 13px;
    }
    .grad-table tr:hover {
        background-color: rgba(128, 128, 128, 0.04);
    }
    .row-header {
        font-weight: bold;
        background-color: rgba(128, 128, 128, 0.06);
        text-align: left !important;
        padding-left: 14px !important;
        font-size: 13.5px !important;
    }
    .text-center {
        text-align: center;
    }
    .text-need {
        color: #e11d48;
        font-weight: bold;
    }
    .text-done {
        color: rgba(128, 128, 128, 0.5);
    }
    </style>
    <div class="grad-container">
    <table class="grad-table">
        <thead>
            <!-- Row 1 -->
            <tr>
                <th rowspan="3">구 분</th>
                <th colspan="6">교 양</th>
                <th colspan="6">전 공</th>
                <th colspan="2">교직</th>
                <th rowspan="3">융합<br>탐색</th>
                <th colspan="2">복수전공</th>
                <th colspan="2">부전공</th>
                <th rowspan="3">졸업<br>학점<br>계</th>
                <th colspan="2">콜라주</th>
            </tr>
            <!-- Row 2 -->
            <tr>
                <th colspan="2">기초교양</th>
                <th rowspan="2">균형<br>교양<br>(선택)</th>
                <th colspan="2">소양교양</th>
                <th rowspan="2">계</th>
                <th colspan="4">최소전공인정학점</th>
                <th rowspan="2">전공<br>심화</th>
                <th rowspan="2">계</th>
                <th rowspan="2">자과</th>
                <th rowspan="2">타과</th>
                <th rowspan="2">필수</th>
                <th rowspan="2">선택</th>
                <th rowspan="2">필수</th>
                <th rowspan="2">선택</th>
                <th rowspan="2">기초</th>
                <th rowspan="2">필수</th>
            </tr>
            <!-- Row 3 -->
            <tr>
                <th>필수</th>
                <th>선택</th>
                <th>필수</th>
                <th>선택</th>
                <th>전공<br>기초</th>
                <th>콜라주</th>
                <th>전공<br>핵심</th>
                <th>소계</th>
            </tr>
        </thead>
        <tbody>
    """)
    
    def get_val(category, subcat, detail, ref_dict):
        try:
            if detail:
                return ref_dict.get(category, {}).get(subcat, {}).get(detail, {}).get("기준", "0"), ref_dict.get(category, {}).get(subcat, {}).get(detail, {}).get("취득", "0")
            elif subcat:
                return ref_dict.get(category, {}).get(subcat, {}).get("기준", "0"), ref_dict.get(category, {}).get(subcat, {}).get("취득", "0")
            else:
                return ref_dict.get(category, {}).get("기준", "0"), ref_dict.get(category, {}).get("취득", "0")
        except Exception:
            return "0", "0"
            
    cols_def = [
        ("교양", "기초교양", "필수"),
        ("교양", "기초교양", "선택"),
        ("교양", "균형교양", "선택"),
        ("교양", "소양교양", "필수"),
        ("교양", "소양교양", "선택"),
        ("교양", "계", None),
        ("전공", "최소전공인정학점", "전공기초"),
        ("전공", "최소전공인정학점", "콜라주"),
        ("전공", "최소전공인정학점", "전공핵심"),
        ("전공", "최소전공인정학점", "소계"),
        ("전공", "전공심화", None),
        ("전공", "계", None),
        ("교직", "자과", None),
        ("교직", "타과", None),
        ("융합탐색", None, None),
        ("복수전공", "필수", None),
        ("복수전공", "선택", None),
        ("부전공", "필수", None),
        ("부전공", "선택", None),
        ("졸업학점계", None, None),
        ("콜라주", "기초", None),
        ("콜라주", "필수", None)
    ]
    
    standards_list = []
    taken_list = []
    diff_list = []
    
    for cat, subcat, det in cols_def:
        std, tkn = get_val(cat, subcat, det, credits)
        standards_list.append(std)
        taken_list.append(tkn)
        
        try:
            std_val = float(std) if "~" not in str(std) else 0
            tkn_val = float(tkn)
            diff = max(0.0, std_val - tkn_val)
            diff_str = f"{int(diff)}" if diff.is_integer() else f"{diff:.1f}"
            if std_val == 0 or "~" in str(std):
                diff_str = "-"
        except Exception:
            diff_str = "-"
        diff_list.append(diff_str)
        
    # 1. 기준학점 행
    html_lines.append("<tr><td class='row-header'>기준학점</td>")
    for std in standards_list:
        html_lines.append(f"<td class='text-center'>{std}</td>")
    html_lines.append("</tr>")
    
    # 2. 취득학점 행
    html_lines.append("<tr><td class='row-header'>취득학점</td>")
    for tkn in taken_list:
        html_lines.append(f"<td class='text-center'>{tkn}</td>")
    html_lines.append("</tr>")
    
    # 3. 부족학점 행
    html_lines.append("<tr><td class='row-header'>부족학점</td>")
    for diff in diff_list:
        if diff != "0" and diff != "-":
            html_lines.append(f"<td class='text-center text-need'>{diff}</td>")
        else:
            html_lines.append("<td class='text-center text-done'>-</td>")
    html_lines.append("</tr>")
    
    html_lines.append("""
        </tbody>
    </table>
    </div>
    """)
    
    st.markdown("".join(html_lines), unsafe_allow_html=True)
else:
    st.info("통합정보시스템(포털) 졸업 학점 정보가 아직 연동되지 않았습니다. 로그아웃 후 다시 로그인해 주세요.")
