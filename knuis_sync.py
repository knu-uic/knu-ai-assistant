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

from db import upsert_user

KNUIS_URL = "https://knuis-s.kongju.ac.kr/index.jsp"

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

def parse_graduation_data(data_frame) -> tuple[str, str, int, dict]:
    """졸업사전예고 프레임에서 학적 마스터 정보와 취득학점 상세 정보를 파싱하여 반환합니다."""
    tables = data_frame.query_selector_all("table")
    
    # 1. 학적 기본정보 표 찾기 (소속학과와 적용학과가 들어있는 표)
    info_table = None
    for table in tables:
        text = table.inner_text()
        if "소속학과" in text and "적용학과" in text:
            info_table = table
            break
            
    if not info_table:
        raise RuntimeError("학적 기본 정보 테이블을 찾지 못했습니다.")
        
    rows_data = info_table.evaluate(r"""
        table => {
            const trs = Array.from(table.querySelectorAll('tr'));
            return trs.map(tr => {
                const cells = Array.from(tr.querySelectorAll('td, th'));
                return cells.map(cell => {
                    const input = cell.querySelector('input, select');
                    if (input) {
                        return input.value.trim();
                    }
                    return cell.innerText.trim().replace(/\xa0/g, ' ').replace(/\n/g, ' ');
                });
            });
        }
    """)
    
    # 키-값 쌍 매핑
    info_dict = {}
    for row_data in rows_data:
        if len(row_data) >= 2:
            for i in range(0, len(row_data) - 1, 2):
                label = row_data[i].strip().replace(" ", "")
                val = row_data[i+1].strip() if i+1 < len(row_data) else ""
                if label:
                    info_dict[label] = val
                    
    student_name = info_dict.get("성명") or "이름 미설정"
    student_major = info_dict.get("소속학과") or "학과 미설정"
    year_str = info_dict.get("학년") or "1"
    
    # "3학년" -> 3 변환
    match = re.search(r"(\d+)", year_str)
    student_year = int(match.group(1)) if match else 1
    
    # 2. 취득학점 요약 표 찾기 (최소전공인정학점이 들어있는 메인 표)
    grad_table = None
    for table in tables:
        text = table.inner_text()
        if "기준학점" in text and "취득학점" in text and "최소전공인정학점" in text:
            grad_table = table
            break
            
    if not grad_table:
        raise RuntimeError("졸업 취득 학점 요약 테이블을 찾지 못했습니다.")
        
    grad_rows = grad_table.query_selector_all("tr")
    standards = None
    taken = None
    
    for row in grad_rows:
        cells = row.query_selector_all("td, th")
        row_data = [c.inner_text().strip().replace('\xa0', ' ').replace('\n', ' ') for c in cells]
        if len(row_data) > 0:
            if "기준학점" in row_data[0]:
                standards = row_data
            elif "취득학점" in row_data[0]:
                taken = row_data
                
    if not standards or not taken:
        raise RuntimeError("기준학점 또는 취득학점 행을 파싱하지 못했습니다.")
        
    def get_val(arr, idx):
        if idx < len(arr):
            val = arr[idx].strip()
            return val if val else "0"
        return "0"
        
    grad_json = {
        "교양": {
            "기초교양": {
                "필수": {"기준": get_val(standards, 1), "취득": get_val(taken, 1)},
                "선택": {"기준": get_val(standards, 2), "취득": get_val(taken, 2)}
            },
            "균형교양": {
                "선택": {"기준": get_val(standards, 3), "취득": get_val(taken, 3)}
            },
            "소양교양": {
                "필수": {"기준": get_val(standards, 4), "취득": get_val(taken, 4)},
                "선택": {"기준": get_val(standards, 5), "취득": get_val(taken, 5)}
            },
            "계": {"기준": get_val(standards, 6), "취득": get_val(taken, 6)}
        },
        "전공": {
            "최소전공인정학점": {
                "전공기초": {"기준": get_val(standards, 7), "취득": get_val(taken, 7)},
                "콜라주": {"기준": get_val(standards, 8), "취득": get_val(taken, 8)},
                "전공핵심": {"기준": get_val(standards, 9), "취득": get_val(taken, 9)},
                "소계": {"기준": get_val(standards, 10), "취득": get_val(taken, 10)}
            },
            "전공심화": {"기준": get_val(standards, 11), "취득": get_val(taken, 11)},
            "계": {"기준": get_val(standards, 12), "취득": get_val(taken, 12)}
        },
        "교직": {
            "자과": {"기준": get_val(standards, 13), "취득": get_val(taken, 13)},
            "타과": {"기준": get_val(standards, 14), "취득": get_val(taken, 14)}
        },
        "융합탐색": {"기준": get_val(standards, 15), "취득": get_val(taken, 15)},
        "복수전공": {
            "필수": {"기준": get_val(standards, 16), "취득": get_val(taken, 16)},
            "선택": {"기준": get_val(standards, 17), "취득": get_val(taken, 17)}
        },
        "부전공": {
            "필수": {"기준": get_val(standards, 18), "취득": get_val(taken, 18)},
            "선택": {"기준": get_val(standards, 19), "취득": get_val(taken, 19)}
        },
        "졸업학점계": {"기준": get_val(standards, 20), "취득": get_val(taken, 20)},
        "콜라주": {
            "기초": {"기준": get_val(standards, 21), "취득": get_val(taken, 21)},
            "필수": {"기준": get_val(standards, 22), "취득": get_val(taken, 22)}
        }
    }
    
    return student_name, student_major, student_year, grad_json

def click_menu_by_value(page, menu_value, timeout_sec=10) -> bool:
    """모든 프레임을 돌며 value 속성에 menu_value가 포함된 요소를 찾아 클릭합니다."""
    print(f"[click_menu] '{menu_value}' 메뉴 클릭 시도 중...", flush=True)
    start_time = time.time()
    selector = f'input[value*="{menu_value}"]'
    while time.time() - start_time < timeout_sec:
        for frame in page.frames:
            try:
                locator = frame.locator(selector)
                if locator.count() > 0 and locator.first.is_visible():
                    print(f"[click_menu] 1차 성공: '{menu_value}' (frame: {frame.url})", flush=True)
                    locator.first.scroll_into_view_if_needed()
                    try:
                        locator.first.click(timeout=2000)
                    except Exception:
                        locator.first.evaluate("el => el.click()")
                    return True
            except Exception:
                continue
        time.sleep(0.5)
    
    print(f"[click_menu] 1차 실패, 2차 일반 text 매칭 탐색 시작 (키워드: {menu_value})", flush=True)
    # 2차 시도: 일반 text 매칭 검색 및 클릭
    start_time = time.time()
    while time.time() - start_time < 5:
        for frame in page.frames:
            try:
                elements = frame.query_selector_all("input, button, a, td, div, span")
                for element in elements:
                    val = element.get_attribute("value") or ""
                    text = element.inner_text() or ""
                    tag = element.evaluate("el => el.tagName")
                    
                    if menu_value in val or menu_value in text:
                        is_vis = element.is_visible()
                        if is_vis:
                            print(f"[click_menu] 2차 매칭 성공 -> 태그: {tag}, value: {val.strip()}, text: {text.strip()}, frame: {frame.url}", flush=True)
                            element.scroll_into_view_if_needed()
                            try:
                                element.click(timeout=2000)
                            except Exception:
                                element.evaluate("el => el.click()")
                            return True
            except Exception:
                continue
        time.sleep(0.5)
        
    print(f"[click_menu] '{menu_value}' 메뉴를 찾지 못함. 현재 가시 프레임들의 텍스트 요약:", file=sys.stderr, flush=True)
    for frame in page.frames:
        try:
            texts = [el.inner_text().strip() for el in frame.query_selector_all("input, a, span, div") if el.is_visible() and el.inner_text().strip()]
            if texts:
                print(f"  - Frame [{frame.url}]: {texts[:10]}...", file=sys.stderr, flush=True)
        except Exception:
            pass
    return False

def parse_timetable_data(context) -> list[dict] | None:
    """모든 페이지와 프레임을 탐색하여 시간표 데이터를 리스트 구조로 반환합니다."""
    saved_data = []
    found_timetable = False

    for page in context.pages:
        for frame in page.frames:
            try:
                tables = frame.query_selector_all("table")
                for table in tables:
                    text = table.inner_text()
                    # 시간표 데이터 식별 키워드
                    if any(kw in text for kw in ["교시", "요일", "교과목", "시간표", "월요일"]):
                        rows = table.evaluate("""
                            table => {
                                const trs = Array.from(table.querySelectorAll('tr'));
                                return trs.map(tr => {
                                    const cells = Array.from(tr.querySelectorAll('td, th'));
                                    return cells.map(cell => cell.innerText.trim().replace(/\\s+/g, ' '));
                                });
                            }
                        """)

                        table_data = []
                        for row in rows:
                            cleaned_cells = [cell for cell in row if cell != ""]
                            if cleaned_cells:
                                table_data.append(row)

                        saved_data.append({
                            "frame_url": frame.url,
                            "frame_name": frame.name or "",
                            "rows": table_data
                        })
                        found_timetable = True
            except Exception:
                continue

    return saved_data if found_timetable else None

def main() -> int:
    parser = argparse.ArgumentParser(description="KNUIS 포털 졸업자가진단 연동")
    parser.add_argument("--username", required=True, help="포털 로그인 아이디 (학번)")
    parser.add_argument("--password-stdin", action="store_true", help="비밀번호를 stdin에서 읽음")
    parser.add_argument("--timeout", type=int, default=60, help="동기화 제한 시간(초)")
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
            browser = p.chromium.launch(headless=True)
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
            knuis_page.wait_for_load_state("load")
            
            # 3. 메뉴 진입
            print("[3/7] 졸업사전예고 메뉴 탐색 중...", flush=True)
            parent_menu_selector = 'input[id="listMenu.menu_nm15"]'
            clicked_parent = wait_and_click_in_any_frame(knuis_page, parent_menu_selector, timeout_sec=15)
            if clicked_parent:
                knuis_page.wait_for_timeout(2000)
                
            menu_selector = 'input[id="listMenu.menu_nm17"]'
            clicked = wait_and_click_in_any_frame(knuis_page, menu_selector, timeout_sec=15)
            if not clicked:
                raise RuntimeError("졸업사전예고(학생) 메뉴를 찾지 못했습니다.")
                
            # 4. 확인 창 클릭
            confirm_selector = 'input[id="Form2.pb1"]'
            clicked = wait_and_click_in_any_frame(knuis_page, confirm_selector, timeout_sec=20)
            if clicked:
                knuis_page.wait_for_timeout(5000)
            else:
                raise RuntimeError("확인 조회 버튼을 찾지 못했습니다.")
                
            # 5. 프레임 파싱
            data_frame = None
            for p_item in context.pages:
                for frame in p_item.frames:
                    try:
                        if "WHHJUV" in frame.url:
                            data_frame = frame
                            break
                    except Exception:
                        continue
                if data_frame:
                    break
                    
            if not data_frame:
                raise RuntimeError("졸업 상세 데이터 프레임(WHHJUV)을 식별하지 못했습니다.")
                
            name, major, year, grad_json = parse_graduation_data(data_frame)
            print(f"학적/졸업 정보 파싱 완료: {name} ({major}, {year}학년)")

            # 6. 시간표 페이지로 이동 및 파싱 (Brute-Force 탐색)
            timetable_json = None
            try:
                print("시간표 조회를 시작합니다...", flush=True)
                
                # 1) 대메뉴 '수업' 클릭 (Contains 검색)
                clicked_parent = click_menu_by_value(knuis_page, "수업")
                if clicked_parent:
                    knuis_page.wait_for_timeout(2000)
                    
                    # 2) 상세메뉴 '시간표' 클릭 (Contains 검색, 수강과목조회 건너뜀)
                    clicked_menu = click_menu_by_value(knuis_page, "시간표")
                    if clicked_menu:
                        knuis_page.wait_for_timeout(4000)
                        
                        # 3) 시간표조회 화면의 조회 버튼 클릭
                        clicked_search = click_menu_by_value(knuis_page, "조회")
                        if clicked_search:
                            knuis_page.wait_for_timeout(4000)
                            
                            # 4) 시간표 데이터 파싱
                            timetable_json = parse_timetable_data(context)
                            print(f"[6/7] 시간표 파싱 완료 (테이블 수: {len(timetable_json) if timetable_json else 0})", flush=True)
                        else:
                            print("시간표 조회 버튼을 클릭하지 못했습니다.", file=sys.stderr, flush=True)
                    else:
                        print("시간표조회 메뉴를 클릭하지 못했습니다.", file=sys.stderr, flush=True)
                else:
                    print("수업 대메뉴를 찾지 못했습니다.", file=sys.stderr, flush=True)
                
            except Exception as te:
                print(f"시간표 연동 중 오류 발생: {te}", file=sys.stderr, flush=True)

            # 7. DB 일괄 저장
            upsert_user(
                student_id=args.username,
                name=name,
                major=major,
                year=year,
                graduation_credits=grad_json,
                timetable=timetable_json
            )
            print(f"포털 데이터 연동 성공 (시간표 연동: {'성공' if timetable_json else '실패'})")
            browser.close()
            return 0
            
    except Exception as e:
        print(f"포털 연동 중 에러 발생: {e}", file=sys.stderr)
        return 1

if __name__ == "__main__":
    sys.exit(main())
