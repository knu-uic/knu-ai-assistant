"""포털 페이지. 통합정보시스템(KNUIS)에서 연동된 취득학점·성적 정보를 한곳에 모아 보여준다."""

import streamlit as st

from ui import get_current_user, render_grade_grid, render_kv_summary

user = get_current_user()

col_title, col_btn = st.columns([5, 2])
with col_title:
    st.title("포털")
    st.caption("통합정보시스템(KNUIS)에서 연동된 취득학점·성적 정보입니다.")
with col_btn:
    st.write("")  # Vertical spacing to align with title
    st.write("")
    with st.popover("🔄 포털 동기화", use_container_width=True):
        st.markdown("**KNUIS 포털 동기화**")
        st.caption("비밀번호는 저장되지 않고 일회성 로그인용으로만 사용됩니다.")
        password = st.text_input("포털 비밀번호", type="password", key="portal_sync_pw")
        if st.button("동기화 시작", type="primary", use_container_width=True):
            if not password:
                st.error("비밀번호를 입력해 주세요.")
            else:
                with st.spinner("포털 정보를 동기화 중이에요(최대 수십 초)…"):
                    from integrations import sync_portal
                    result = sync_portal(user["student_id"], password)
                    if result.returncode == 0:
                        st.success("동기화 성공!")
                        st.rerun()
                    else:
                        st.error(result.stderr.strip() or result.stdout.strip() or "동기화에 실패했어요.")

credits = user.get("graduation_credits")
grade_distribution = user.get("grade_distribution")
cumulative_grades = user.get("cumulative_grades")

# 포털 미연동 안내 (홈 시간표 미연동 안내와 동일 톤)
if not (credits or grade_distribution or cumulative_grades):
    st.info("통합정보시스템(포털)이 아직 연동되지 않았습니다. 설정 페이지에서 포털을 연동하면 학적·성적 정보가 표시됩니다.")
    st.stop()

# ── 취득학점 현황 (profile.py에서 이전) ─────────────────────────
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

# ── 나의 성적분포 ──────────────────────────────────────────────
if grade_distribution and grade_distribution.get("grids"):
    st.markdown("---")
    st.subheader("📊 나의 성적분포")
    render_kv_summary(grade_distribution.get("summary"))
    for grid in grade_distribution["grids"].values():
        render_grade_grid(grid)

# ── 누적 성적 ──────────────────────────────────────────────────
if cumulative_grades and cumulative_grades.get("grids"):
    st.markdown("---")
    st.subheader("📚 누적 성적")
    for grid in cumulative_grades["grids"].values():
        render_grade_grid(grid)
