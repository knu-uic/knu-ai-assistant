"""KNUIS 통합정보시스템 졸업 자가진단 학점 및 학적 마스터 정보 동기화.

LMS 로그인 정보(동일 ID/PW)를 입력받아 포털에 headless로 로그인한 후
공식 학적 정보(성명, 학과, 학년)와 졸업 취득 학점 현황을 DB에 저장합니다.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import time
from pathlib import Path
from playwright.sync_api import sync_playwright

from sync.common import DEFAULT_PORTAL_URL
from db import upsert_user

KNUIS_URL = DEFAULT_PORTAL_URL

def wait_and_click_in_any_frame(page, selector, timeout_sec=15) -> bool:
    """모든 iframe을 탐색하며 지정된 요소를 찾아 화면에 나타나면 클릭합니다."""
    start_time = time.time()
    while time.time() - start_time < timeout_sec:
        for frame in page.frames:
            try:
                locator = frame.locator(selector)
                if locator.count() > 0 and locator.first.is_visible():
                    locator.first.scroll_into_view_if_needed()
                    locator.first.click()
                    return True
            except Exception:
                continue
        time.sleep(0.5)
    return False

def open_menu(page, menu_id, timeout_sec=120) -> bool:
    """좌측 LeftFrame의 Page00.funcLeft.fn_runFileMDI를 직접 호출해 화면에 진입.
    가상화 메뉴 트리 스크롤/라이브값 매칭(click_left_menu) 대신, 콘솔 후킹으로 역추적한
    menuId로 곧장 MDI 페이지를 연다. 메뉴 항목이 다 채워질 때까지 기다릴 필요 없이
    fn_runFileMDI 함수가 정의되는 즉시 호출 가능하므로 진입이 빠르고 안정적이다.

    프레임 접근은 Playwright page.frame(name=...) 대신 top 컨텍스트에서
    #LeftFrame 엘리먼트의 contentWindow로 직접 진입한다. 통합정보시스템 진입 직후
    LeftFrame이 여러 번 리로드되는 동안 page.frame 핸들은 'execution context destroyed'로
    불안정하지만, top에서 매번 querySelector로 새로 잡으면 첫 진입도 안정적으로 호출된다."""
    deadline = time.time() + timeout_sec
    while time.time() < deadline:
        try:
            ok = page.evaluate("""(id) => {
                const w = document.querySelector('#LeftFrame')?.contentWindow;
                if (w && w.Page00 && w.Page00.funcLeft && w.Page00.funcLeft.fn_runFileMDI) {
                    w.Page00.funcLeft.fn_runFileMDI(id, 0);
                    return true;
                }
                return false;
            }""", menu_id)
            if ok:
                print(f"[open_menu] fn_runFileMDI('{menu_id}', 0) 호출 완료", flush=True)
                return True
        except Exception:
            pass
        time.sleep(0.5)
    print(f"[open_menu] LeftFrame.fn_runFileMDI를 {timeout_sec}초 안에 준비하지 못함 (menuId={menu_id})", file=sys.stderr, flush=True)
    return False


# 졸업 G4 86컬럼 → grad_json 슬롯 매핑.
# (grad_json 경로, 기준 컬럼(SUST_*), 취득 컬럼). 컬럼=None이면 "0".
# arrData 컬럼명이 명시적이라 DOM 위치파싱에서 어긋났던 교직/융합탐색 정렬 문제가 바로잡힌다.
# 실제 포털 레이아웃 대조로 확정: 교직=단일(PRO), 콜라주=자과/타과(기준 A_COL_*, 취득 COL_*).
GRAD_G4_MAP = [
    (("교양", "기초교양", "필수"), "SUST_BASIC_CUL_ESSEN", "BASIC_CUL_ESSEN"),
    (("교양", "기초교양", "선택"), "SUST_BASIC_CUL_CHOOSE", "BASIC_CUL_CHOOSE"),
    (("교양", "균형교양", "선택"), "SUST_BAL_CUL_CHOOSE", "BAL_CUL_CHOOSE"),
    (("교양", "소양교양", "필수"), "SUST_ACCOM_CUL_ESSEN", "ACCOM_CUL_ESSEN"),
    (("교양", "소양교양", "선택"), "SUST_ACCOM_CUL_CHOOSE", "ACCOM_CUL_CHOOSE"),
    (("교양", "계"), "SUST_CUL_SUM", "CUL_SUM"),
    (("전공", "최소전공인정학점", "전공기초"), "SUST_SUB_BGN", "SUB_BGN"),
    (("전공", "최소전공인정학점", "콜라주"), "SUST_COL", "COL"),
    (("전공", "최소전공인정학점", "전공핵심"), "SUST_SUB_KEY", "SUB_KEY"),
    (("전공", "최소전공인정학점", "소계"), "SUST_SUB_SUM1", "SUB_SUM1"),
    (("전공", "전공심화"), "SUST_SUB_DEEP", "SUB_DEEP"),
    (("전공", "계"), "SUST_SUB_SUM2", "SUB_SUM2"),
    (("교직",), "SUST_PRO", "PRO"),
    (("융합탐색",), "SUST_FUSION_RESER", "FUSION_RESER"),
    (("복수전공", "기초"), "DOU_BGN_LCTPT", "DOU_SUB_BGN"),
    (("복수전공", "필수"), "DOU_ESSEN_LCTPT", "DOU_SUB_ESSEN"),
    (("복수전공", "선택"), "DOU_CHOOSE_LCTPT", "DOU_SUB_CHOOSE"),
    (("부전공", "필수"), "MIN_ESSEN_LCTPT", "MIN_SUB_ESSEN"),
    (("부전공", "선택"), "MIN_CHOOSE_LCTPT", "MIN_SUB_CHOOSE"),
    (("졸업학점계",), "SUST_TOT_SUM", "TOT_SUM"),
    (("콜라주", "자과"), "A_COL_SELF", "COL_SELF"),
    (("콜라주", "타과"), "A_COL_OTHER", "COL_OTHER"),
]


def _set_nested(d, path, value):
    """중첩 dict의 path 경로에 value 설정. 중간 노드 없으면 생성."""
    for key in path[:-1]:
        d = d.setdefault(key, {})
    d[path[-1]] = value


def parse_graduation_data(data_frame) -> tuple[str, str, int, dict]:
    """졸업사전예고 프레임에서 학적(F_SRCH)·취득학점(G4)을 arrData에서 직접 파싱.
    grad_json 중첩 구조는 기존과 동일하게 유지(portal.py cols_def 호환)."""
    # 1. 학적 기본정보 — F_SRCH arrData (NM/SUST_NM/SYEAR)
    f = get_arrdata(data_frame, "F_SRCH")
    if not f:
        raise RuntimeError("학적 기본 정보(F_SRCH arrData)를 찾지 못했습니다.")
    student_name = _av(f, "NM", 0) or "이름 미설정"
    student_major = _av(f, "SUST_NM", 0) or "학과 미설정"
    year_str = _av(f, "SYEAR", 0) or "1"
    match = re.search(r"(\d+)", year_str)
    student_year = int(match.group(1)) if match else 1

    # 2. 취득학점 요약 — G4 arrData(1행). SUST_*=기준, 접두사 없음=취득.
    g4 = get_arrdata(data_frame, "G4")
    if not g4:
        raise RuntimeError("졸업 취득 학점 요약(G4 arrData)을 찾지 못했습니다.")

    def cell(col):
        if col is None:
            return "0"
        v = _av(g4, col, 0)
        return v if v else "0"

    grad_json = {}
    for path, std_col, taken_col in GRAD_G4_MAP:
        _set_nested(grad_json, path, {"기준": cell(std_col), "취득": cell(taken_col)})

    return student_name, student_major, student_year, grad_json


def find_frame_by_url_substr(context, substr):
    """모든 페이지·프레임을 훑어 URL에 substr이 포함된 첫 프레임을 반환. 못 찾으면 None."""
    for p_item in context.pages:
        for frame in p_item.frames:
            try:
                if substr in frame.url:
                    return frame
            except Exception:
                continue
    return None


def find_frame_by_iframe_id(context, iframe_id):
    """iframe DOM 엘리먼트의 id/name으로 Frame을 찾아 반환. 못 찾으면 None.
    MDI 화면 iframe URL이 공통 실행주소(run.jsp 등)로만 떠 url-substr 매칭이 실패하는
    환경 대비. 화면 id가 iframe id 속성에 박혀 있으면 이 방식이 안정적이다."""
    for p_item in context.pages:
        for frame in p_item.frames:
            try:
                element = frame.frame_element()
                fid = element.get_attribute("id")
                fname = element.get_attribute("name")
                if fid == iframe_id or fname == iframe_id:
                    return frame
            except Exception:
                continue
    return None


def get_arrdata(frame, grid_id) -> dict | None:
    """Webcrea 런타임 객체의 arrData(컬럼지향 {COL:[v0,v1,...]})를 직접 반환.
    렌더된 DOM 대신 데이터셋을 직접 읽어 가상화로 인한 행 누락 없이 전체 행을 가져온다.
    Webcrea/객체/arrData 없으면 None(진입 실패·미지원 화면 가드)."""
    try:
        return frame.evaluate("""(gid) => {
            if (!window.Webcrea) return null;
            let o;
            try { o = Webcrea.GetObjectById(gid); } catch (e) { return null; }
            if (!o || !o.arrData) return null;
            const out = {};
            for (const k of Object.keys(o.arrData)) {
                if (k === '_my_data_seq_') continue;
                out[k] = o.arrData[k];
            }
            return out;
        }""", grid_id)
    except Exception:
        return None


def _av(arr, col, i) -> str:
    """arrData의 col 컬럼 i번째 값을 문자열로. 없으면 빈 문자열."""
    seq = arr.get(col)
    if seq is None or i >= len(seq):
        return ""
    v = seq[i]
    return "" if v is None else str(v)


def _arr_len(arr, cols) -> int:
    """주어진 컬럼들 중 최대 길이 = 행 수."""
    return max((len(arr[c]) for c in cols if arr.get(c) is not None), default=0)


def _build_grid(arr, specs, code_map, title) -> dict:
    """arrData를 {title, columns, rows} 그리드로 변환.
    specs: list[(표시라벨, arrData_컬럼, is_code)]. is_code면 _NM 짝이 없는 코드라
    code_map으로 디코딩(예: 등급 GRD_CD)."""
    columns = [label for label, _, _ in specs]
    n = _arr_len(arr, [src for _, src, _ in specs])
    rows = []
    for i in range(n):
        row = []
        for _, src, is_code in specs:
            v = _av(arr, src, i)
            if is_code and v:
                v = code_map.get(v, v)
            row.append(v)
        rows.append(row)
    return {"title": title, "columns": columns, "rows": rows}


def _build_code_map(frame) -> dict:
    """Webcrea 셀렉트박스(_my_selectbox)의 모든 항목에서 code→라벨 맵을 추출.
    등급(GRD_CD)·이수구분(POBT_FG_CD) 등 Combo Box 셀은 화면값이 code 속성에만 있어
    이 맵으로 디코딩해야 한다."""
    try:
        return frame.evaluate("""() => {
            const m = {};
            document.querySelectorAll('li[role="selectboxitem"]').forEach(li => {
                const c = li.getAttribute('code');
                if (c) m[c] = (li.getAttribute('svalue') || li.innerText || '').trim();
            });
            return m;
        }""")
    except Exception:
        return {}


def wait_for_grid_rows(context, frame_substr, grid_id, timeout_sec=20):
    """frame_substr 프레임이 등장하고 <grid_id>.Data0 행이 렌더될 때까지 polling.
    Webcrea Submission(crossurl.jsp) 응답 전에 파싱하면 빈 프레임을 긁으므로 필요."""
    deadline = time.time() + timeout_sec
    while time.time() < deadline:
        frame = find_frame_by_url_substr(context, frame_substr)
        if frame is not None:
            try:
                if frame.query_selector(f'tr[id="{grid_id}.Data0"]') is not None:
                    return frame
            except Exception:
                pass
        time.sleep(0.5)
    return find_frame_by_url_substr(context, frame_substr)


# 성적분포 G1: arrData 컬럼은 이미 한글. (표시라벨, arrData컬럼, is_code)
GRADE_DIST_G1_SPEC = [
    ("년도", "년도", False),
    ("학기", "학기명", False),
    ("신청", "신청학점", False),
    ("취득", "취득학점", False),
    ("평균평점", "평점평균", False),
    ("환산점수", "백분위평균점수", False),
    ("학과평균", "학과평균", False),
    ("학과등수", "학과등수", False),
    ("대학평균", "대학평균", False),
    ("대학등수", "대학등수", False),
    ("학사경고", "학사경고", False),
]
# 성적분포 F1 요약: (표시라벨, arrData컬럼). 기존 DOM summary 라벨과 동일.
GRADE_DIST_F1_SPEC = [
    ("총신청 학점", "APLY_LCTPT"),
    ("총 취득학점", "ACQ_LCTPT"),
    ("평점계", "SUM_AVRP"),
    ("평점평균", "F_INC_AVRP_AVG"),
    ("환산점수", "PCNT_AVG_SCR"),
]


def parse_grade_distribution(context) -> dict | None:
    """WHHSJV0275(나의성적분포): G1(학기별 성적) + F1(전체 요약)을 arrData에서 직접 파싱."""
    frame = find_frame_by_iframe_id(context, "WHHSJV0275") or find_frame_by_url_substr(context, "WHHSJV0275")
    if frame is None:
        print("[grade_distribution] WHHSJV0275 프레임을 찾지 못했습니다.", file=sys.stderr, flush=True)
        return None
    code_map = _build_code_map(frame)
    grids = {}
    g1 = get_arrdata(frame, "G1")
    if g1:
        grid = _build_grid(g1, GRADE_DIST_G1_SPEC, code_map, "학기별 성적")
        if grid["rows"]:
            grids["G1"] = grid
    f1 = get_arrdata(frame, "F1")
    summary = None
    if f1:
        summary = [[label, _av(f1, src, 0)] for label, src in GRADE_DIST_F1_SPEC]
    if not grids and not summary:
        print("[grade_distribution] 파싱 결과가 비어 있습니다.", file=sys.stderr, flush=True)
        return None
    return {"frame_url": frame.url, "grids": grids, "summary": summary}


def select_semester_all(page) -> bool:
    """누적성적조회 페이지의 학기 dropdown을 '전체'로 강제 선택. 성공 여부 반환."""
    for frame in page.frames:
        try:
            selects = frame.query_selector_all("select")
            for sel in selects:
                try:
                    options = sel.evaluate("el => Array.from(el.options).map(o => o.text)")
                except Exception:
                    options = []
                if "전체" in options:
                    try:
                        sel.select_option(label="전체")
                        print(f"[select_semester_all] '전체' 선택 성공 (frame: {frame.url})", flush=True)
                        return True
                    except Exception:
                        try:
                            sel.evaluate("(el) => { for (const o of el.options) { if (o.text === '전체') { el.value = o.value; el.dispatchEvent(new Event('change', {bubbles:true})); break; } } }")
                            print(f"[select_semester_all] '전체' 선택 (evaluate fallback) (frame: {frame.url})", flush=True)
                            return True
                        except Exception:
                            continue
        except Exception:
            continue
    print("[select_semester_all] '전체' 옵션이 있는 select를 찾지 못함. 디폴트 유지.", file=sys.stderr, flush=True)
    return False


# 누적성적 그리드 스펙: (표시라벨, arrData컬럼, is_code).
# 이수구분·과목명 등은 _NM 한글짝을 직접 사용, 등급(GRD_CD)·이수구분코드는 _NM 없어 code_map 디코딩.
CUMULATIVE_G1_SPEC = [
    ("년도", "TLSN_YYYY", False),
    ("학기", "TLSN_SHTM_NM", False),
    ("학년", "SYEAR", False),
    ("이수구분", "POBT_FG_NM", False),
    ("과목코드", "SUBJ_CD", False),
    ("과목명", "SUBJ_NM", False),
    ("학점", "LCTPT", False),
    ("등급", "GRD_CD", True),
    ("평점", "AVRP", False),
    # 결석(ABSN_FRQ): 포털 화면엔 숨겨진 컬럼이지만 arrData엔 있어 우리 앱에서 추가 노출.
    ("결석", "ABSN_FRQ", False),
    ("교양교육과정", "APLY_POBT_SFG_CD_NM", False),
    ("재수강", "RETLSN_YN", True),
    ("재수강과목명", "RETLSN_SUBJ_NM", False),
]
CUMULATIVE_G2_SPEC = [
    ("년도", "YYYY", False),
    ("학기", "SHTM_NM", False),
    ("신청", "APLY_LCTPT", False),
    ("취득", "ACQ_LCTPT", False),
    ("평점", "F_INC_AVRP_AVG", False),
    ("환산점수", "PCNT_AVG_SCR", False),
    ("학사경고", "BCH_WARN_YN", True),
]
CUMULATIVE_G3_SPEC = [
    ("이수구분", "POBT_FG_CD", True),
    ("졸업소요", "POBT_LCTPT", False),
    ("인정", "APPROVAL_LCTPT", False),
    ("신청", "VIEW_APLY_LCTPT", False),
    ("취득", "VIEW_ACQ_LCTPT", False),
    ("과부족", "LCK_LCTPT", False),
    ("평점", "AVG_AVRP", False),
]
CUMULATIVE_GRIDS = [
    ("G1", "과목별 성적", CUMULATIVE_G1_SPEC),
    ("G2", "학기별 성적", CUMULATIVE_G2_SPEC),
    ("G3", "이수구분별 학점", CUMULATIVE_G3_SPEC),
]


def parse_cumulative_grades(context) -> dict | None:
    """WHHSJV0270(누적성적조회): G1(과목별)·G2(학기별)·G3(이수구분별)을 arrData에서 직접 파싱."""
    frame = find_frame_by_iframe_id(context, "WHHSJV0270") or find_frame_by_url_substr(context, "WHHSJV0270")
    if frame is None:
        print("[cumulative_grades] WHHSJV0270 프레임을 찾지 못했습니다.", file=sys.stderr, flush=True)
        return None
    code_map = _build_code_map(frame)
    grids = {}
    for gid, title, spec in CUMULATIVE_GRIDS:
        arr = get_arrdata(frame, gid)
        if not arr:
            continue
        grid = _build_grid(arr, spec, code_map, title)
        if grid["rows"]:
            grids[gid] = grid
    if not grids:
        print("[cumulative_grades] 파싱 결과가 비어 있습니다.", file=sys.stderr, flush=True)
        return None
    return {"frame_url": frame.url, "grids": grids}


# 시간표 G1 arrData: LTTM_CD(교시) + MON~SAT(요일별 셀). MON 값에 '과목(분반 교수) 강의실'이
# 모두 들어있고 *_SUST 컬럼은 강의코드(C4T010 등)라 표시에 불필요해 무시한다.
TIMETABLE_DAYS = [("MON", "월요일"), ("TUE", "화요일"), ("WED", "수요일"),
                  ("THU", "목요일"), ("FRI", "금요일"), ("SAT", "토요일")]


def _tt_clean(s: str) -> str:
    # home.py가 교시 셀을 split(" ")[0]로 자르고 요일 셀은 정규식(\s* 허용)으로 파싱하므로
    # <br>·개행·\xa0를 모두 단일 공백으로 정규화한다(기존 DOM의 \s+→space와 동일).
    return re.sub(r"\s+", " ", s.replace("<br>", " ").replace("\xa0", " ")).strip()


def parse_timetable_data(context) -> list[dict] | None:
    """시간표 WHHSKV 프레임의 G1 arrData를 직접 읽어 행 추출.
    출력 shape은 기존과 동일(list[{frame_url, frame_name, rows}], rows[0]은 헤더)이어야
    home.py 시간표 렌더(rows[0]에 '월요일/교시' 매칭, 셀 정규식 파싱)가 그대로 동작한다."""
    frame = find_frame_by_iframe_id(context, "WHHSKV0580") or find_frame_by_url_substr(context, "WHHSKV")
    if frame is None:
        print("[timetable] WHHSKV 프레임을 찾지 못했습니다.", file=sys.stderr, flush=True)
        return None
    arr = get_arrdata(frame, "G1")
    if not arr or not arr.get("LTTM_CD"):
        print("[timetable] G1 arrData를 얻지 못했습니다.", file=sys.stderr, flush=True)
        return None
    n = len(arr["LTTM_CD"])
    header = ["교시"] + [label for _, label in TIMETABLE_DAYS]
    rows = [header]
    for i in range(n):
        period = _tt_clean(_av(arr, "LTTM_CD", i))
        row = [period] + [_tt_clean(_av(arr, day, i)) for day, _ in TIMETABLE_DAYS]
        rows.append(row)
    return [{"frame_url": frame.url, "frame_name": frame.name or "", "rows": rows}]

def main() -> int:
    parser = argparse.ArgumentParser(description="KNUIS 포털 졸업자가진단 연동")
    parser.add_argument("--username", required=True, help="포털 로그인 아이디 (학번)")
    parser.add_argument("--password-stdin", action="store_true", help="비밀번호를 stdin에서 읽음")
    parser.add_argument("--timeout", type=int, default=60, help="동기화 제한 시간(초)")
    parser.add_argument("--headed", action="store_true", help="브라우저를 화면에 띄움(시각 검증용)")
    parser.add_argument("--slow-mo", type=int, default=0, help="각 동작 사이 지연(ms). 디버그/시각 검증용")
    parser.add_argument("--keep-open", type=int, default=0, help="작업 종료 후 브라우저를 N초 동안 닫지 않음(시각 검증용)")
    parser.add_argument("--no-db", action="store_true", help="DB 저장 단계를 건너뛰고 파싱 결과만 stdout에 요약 출력(시각 검증용)")
    args = parser.parse_args()

    if args.password_stdin:
        password = sys.stdin.readline().rstrip("\n")
    else:
        print("비밀번호 입력 파라미터가 유효하지 않습니다. --password-stdin을 사용하세요.", file=sys.stderr)
        return 1

    if not password:
        print("비밀번호가 비어있습니다.", file=sys.stderr)
        return 1

    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=not args.headed, slow_mo=args.slow_mo)
            context = browser.new_context(
                viewport={"width": 1280, "height": 800},
                user_agent="Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
            )
            page = context.new_page()
            
            # 1. 로그인 단계
            print("[1/7] 포털 로그인 시도 중...", flush=True)
            
            # Dialog(알럿창 등) 이벤트 감지 추가
            def handle_dialog(dialog):
                print(f"[1/7] [브라우저 알림창 발생] 메시지: {dialog.message}", file=sys.stderr, flush=True)
                dialog.accept()
            page.on("dialog", handle_dialog)
            
            page.goto(KNUIS_URL)
            id_selector = 'input[id="frmIlban.sg_uid"]'
            pw_selector = 'input[id="frmIlban.sg_pwd"]'
            btn_selector = 'input[id="frmIlban.pb_i_login"]'
            
            page.wait_for_selector(id_selector, timeout=15000)
            page.fill(id_selector, args.username)
            page.fill(pw_selector, password)
            print(f"[1/7] 로그인 입력 폼 작성 완료 (ID: {args.username})", flush=True)
            page.click(btn_selector)
            
            # 대기 및 새로고침 (포털 구조상 필수)
            print("[1/7] 로그인 클릭 후 리다이렉트 대기 (4초)...", flush=True)
            page.wait_for_timeout(4000)
            print(f"[1/7] 대기 완료 후 현재 URL: {page.url}", flush=True)
            
            print("[1/7] 통합정보시스템 진입을 위한 새로고침(Reload) 시도...", flush=True)
            page.reload()
            page.wait_for_load_state("load")
            print(f"[1/7] 새로고침 완료 후 현재 URL: {page.url}", flush=True)
            page.wait_for_timeout(2000)
            
            # 2. 통합정보시스템 진입
            print("[2/7] 통합정보시스템 버튼 탐색 중...", flush=True)
            sys_btn_selector = 'img[id="frmsystem_s.imgsys1"]'
            
            # 현재 페이지 프레임 URL 정보 로깅
            frame_urls = [f.url for f in page.frames]
            print(f"[2/7] 현재 페이지 전체 프레임 URL 목록: {frame_urls}", flush=True)
            
            with context.expect_page() as new_page_info:
                clicked = wait_and_click_in_any_frame(page, sys_btn_selector, timeout_sec=15)
                if not clicked:
                    print("[2/7] 1차 이미지 버튼 ID로 클릭 실패. 2차 alt 텍스트로 시도...", flush=True)
                    clicked = wait_and_click_in_any_frame(page, 'img[alt="통합정보시스템"]', timeout_sec=5)
                if not clicked:
                    # 최종 실패 시 디버깅을 위한 HTML 정보 출력
                    print("[2/7] 통합정보시스템 버튼 클릭 실패. 최종 바디 텍스트 길이:", len(page.content()), file=sys.stderr, flush=True)
                    raise RuntimeError("통합정보시스템 진입 버튼을 찾지 못했습니다.")
                    
            knuis_page = new_page_info.value
            knuis_page.bring_to_front()
            knuis_page.wait_for_load_state("load")

            # LeftFrame의 fn_runFileMDI 런타임이 준비될 때까지 대기(최대 120초, 준비 즉시 통과).
            # 느린 환경에서 첫 메뉴 진입이 런타임 미초기화로 빈손이 되는 것을 막는다.
            print("[2/7] LeftFrame 런타임 준비 대기 중...", flush=True)
            for _ in range(120):
                try:
                    if knuis_page.evaluate("""() => {
                        const w = document.querySelector('#LeftFrame')?.contentWindow;
                        return !!(w && w.Page00 && w.Page00.funcLeft && w.Page00.funcLeft.fn_runFileMDI);
                    }"""):
                        print("[2/7] LeftFrame 런타임 준비 완료", flush=True)
                        break
                except Exception:
                    pass
                knuis_page.wait_for_timeout(1000)
            else:
                print("[2/7] LeftFrame 런타임 준비 타임아웃(계속 진행).", file=sys.stderr, flush=True)

            # 3. 시간표(menuId 1000000062) — fn_runFileMDI 직접 호출로 진입.
            timetable_json = None
            try:
                print("[3/8] 시간표 진입 (fn_runFileMDI)...", flush=True)
                open_menu(knuis_page, "1000000062")
                knuis_page.wait_for_timeout(3000)
                wait_for_grid_rows(context, "WHHSKV", "G1", timeout_sec=30)
                timetable_json = parse_timetable_data(context)
                print(f"[3/8] 시간표 파싱 완료 (테이블 수: {len(timetable_json) if timetable_json else 0})", flush=True)
            except Exception as te:
                print(f"시간표 연동 중 오류 발생: {te}", file=sys.stderr, flush=True)

            # 4. 나의 성적분포(menuId 1000000103) — 조회 버튼 없이 진입 즉시 crossurl 로드.
            grade_distribution_json = None
            try:
                print("[4/8] 나의 성적분포 진입 (fn_runFileMDI)...", flush=True)
                open_menu(knuis_page, "1000000103")
                knuis_page.wait_for_timeout(3000)
                wait_for_grid_rows(context, "WHHSJV0275", "G1", timeout_sec=30)
                grade_distribution_json = parse_grade_distribution(context)
                print(f"[4/8] 나의 성적분포 파싱 완료 (그리드 수: {len(grade_distribution_json['grids']) if grade_distribution_json else 0})", flush=True)
            except Exception as ge:
                print(f"나의 성적분포 연동 중 오류 발생: {ge}", file=sys.stderr, flush=True)

            # 5. 누적성적조회(menuId 1000000102) ('전체' 학기 강제 선택)
            cumulative_grades_json = None
            try:
                print("[5/8] 누적성적조회 진입 (fn_runFileMDI)...", flush=True)
                open_menu(knuis_page, "1000000102")
                knuis_page.wait_for_timeout(3000)
                select_semester_all(knuis_page)
                knuis_page.wait_for_timeout(500)
                # 조회 버튼(F_TOPMENU.BTN_SRCH)을 직접 실행해 '전체' 학기 그리드 갱신을 확실히 트리거.
                # 진입만으로 그리드가 비어 있는 경우(조회 미발생) 빈손 파싱을 막는다.
                cg_frame = find_frame_by_iframe_id(context, "WHHSJV0270") or find_frame_by_url_substr(context, "WHHSJV0270")
                if cg_frame is not None:
                    try:
                        cg_frame.evaluate("""() => {
                            const b = window.Page00?.F_TOPMENU?.BTN_SRCH;
                            if (b && b.OnCLICK) b.OnCLICK();
                        }""")
                    except Exception:
                        pass
                wait_for_grid_rows(context, "WHHSJV0270", "G1", timeout_sec=20)
                cumulative_grades_json = parse_cumulative_grades(context)
                print(f"[5/8] 누적성적조회 파싱 완료 (그리드 수: {len(cumulative_grades_json['grids']) if cumulative_grades_json else 0})", flush=True)
            except Exception as ce:
                print(f"누적성적조회 연동 중 오류 발생: {ce}", file=sys.stderr, flush=True)

            # 6. 졸업사전예고(menuId 1000000111): 학적(#F_SRCH) + 졸업 취득학점(#G4).
            #    진입 시 WHHJUV0942 안내문 팝업이 뜨지만 모달 오버레이일 뿐, 데이터는 뒤 프레임
            #    DOM에 이미 렌더되므로 팝업을 닫지 않고 evaluate로 직접 읽는다(안내문 닫기는 best-effort).
            #    졸업사전예고 실패가 시간표·성적 저장을 막지 않도록 비치명적 처리.
            name, major, year, grad_json = None, None, None, None
            try:
                print("[6/8] 졸업사전예고 진입 (fn_runFileMDI)...", flush=True)
                open_menu(knuis_page, "1000000111")
                knuis_page.wait_for_timeout(3000)
                # 안내문 팝업 '확인' 닫기 시도(실패해도 무시 — DOM 읽기에 영향 없음).
                wait_and_click_in_any_frame(knuis_page, 'input[value*="확인"]', timeout_sec=3)

                # G4 arrData를 실제로 가진 WHHJUV 프레임 선택. #G4 DOM은 shell 프레임에도 있을 수
                # 있어, Webcrea 런타임+arrData 적재가 모두 끝난 프레임을 직접 검증해야 한다
                # (안내문 팝업 프레임 구분 + 데이터 로드 대기 동시 처리).
                data_frame = None
                deadline = time.time() + 20
                while time.time() < deadline and data_frame is None:
                    for p_item in context.pages:
                        for frame in p_item.frames:
                            try:
                                # URL이 공통 실행주소(run.jsp 등)로 떠도 잡히도록 URL 프리필터 제거.
                                # 단 #G4만 가진 shell 프레임이 있어, 학적(F_SRCH)+취득학점(G4)을
                                # 모두 보유한 프레임만 데이터 프레임으로 확정한다.
                                if get_arrdata(frame, "F_SRCH") and get_arrdata(frame, "G4"):
                                    data_frame = frame
                                    break
                            except Exception:
                                continue
                        if data_frame:
                            break
                    if data_frame is None:
                        time.sleep(0.5)

                if not data_frame:
                    raise RuntimeError("졸업 데이터 프레임(G4 arrData 보유 WHHJUV)을 식별하지 못했습니다.")

                name, major, year, grad_json = parse_graduation_data(data_frame)
                print(f"[6/8] 학적/졸업 정보 파싱 완료: {name} ({major}, {year}학년)")
            except Exception as gae:
                print(f"졸업사전예고 연동 중 오류 발생(무시): {gae}", file=sys.stderr, flush=True)

            # 7. DB 일괄 저장
            if args.no_db:
                print("[7/7] --no-db 지정으로 DB 저장 단계 건너뜀. 파싱 결과 요약만 출력합니다.", flush=True)
                print(f"  · 학적: name={name}, major={major}, year={year}")
                print(f"  · 졸업학점: {'존재' if grad_json else 'NULL'}")
                print(f"  · 시간표 테이블 수: {len(timetable_json) if timetable_json else 0}")
                if grade_distribution_json:
                    for gid, g in grade_distribution_json.get("grids", {}).items():
                        print(f"    [성적분포 {gid}:{g['title']}] cols={g['columns']}, rows={len(g['rows'])}, head={g['rows'][0] if g['rows'] else []}")
                    if grade_distribution_json.get("summary"):
                        print(f"    [성적분포 summary] {grade_distribution_json['summary']}")
                if cumulative_grades_json:
                    for gid, g in cumulative_grades_json.get("grids", {}).items():
                        print(f"    [누적성적 {gid}:{g['title']}] cols={g['columns']}, rows={len(g['rows'])}, head={g['rows'][0] if g['rows'] else []}")
                # 전체 행을 눈으로 확인할 수 있도록 파싱 결과 전체를 JSON 파일로 덤프.
                import json as _json
                import os as _os
                _os.makedirs("output", exist_ok=True)
                _dump_path = f"output/grades_dump_{args.username}.json"
                with open(_dump_path, "w", encoding="utf-8") as _f:
                    _json.dump({
                        "timetable": timetable_json,
                        "grade_distribution": grade_distribution_json,
                        "cumulative_grades": cumulative_grades_json,
                    }, _f, ensure_ascii=False, indent=2)
                print(f"[7/7] 전체 파싱 결과 덤프 저장: {_dump_path}", flush=True)
            else:
                upsert_user(
                    student_id=args.username,
                    name=name,
                    major=major,
                    year=year,
                    graduation_credits=grad_json,
                    timetable=timetable_json,
                    grade_distribution=grade_distribution_json,
                    cumulative_grades=cumulative_grades_json,
                )
            print(
                f"포털 데이터 연동 성공 "
                f"(시간표: {'성공' if timetable_json else '실패'}, "
                f"성적분포: {'성공' if grade_distribution_json else '실패'}, "
                f"누적성적: {'성공' if cumulative_grades_json else '실패'})"
            )
            if args.keep_open > 0:
                print(f"[keep-open] 브라우저를 {args.keep_open}초 동안 유지합니다(시각 확인용)...", flush=True)
                time.sleep(args.keep_open)
            browser.close()
            return 0
            
    except Exception as e:
        print(f"포털 연동 중 에러 발생: {e}", file=sys.stderr)
        return 1

if __name__ == "__main__":
    sys.exit(main())
