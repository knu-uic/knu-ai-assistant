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

def parse_and_save_data(student_id: str, data_frame) -> tuple[str, str, int, dict]:
    """졸업사전예고 프레임에서 학적 마스터 정보와 취득학점 상세 정보를 파싱 및 저장합니다."""
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
        
    rows_data = info_table.evaluate("""
        table => {
            const trs = Array.from(table.querySelectorAll('tr'));
            return trs.map(tr => {
                const cells = Array.from(tr.querySelectorAll('td, th'));
                return cells.map(cell => {
                    const input = cell.querySelector('input, select');
                    if (input) {
                        return input.value.trim();
                    }
                    return cell.innerText.trim().replace(/\\xa0/g, ' ').replace(/\\n/g, ' ');
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
    
    # 3. DB 반영
    upsert_user(
        student_id=student_id,
        name=student_name,
        major=student_major,
        year=student_year,
        graduation_credits=grad_json
    )
    
    return student_name, student_major, student_year, grad_json

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
            page.goto(KNUIS_URL)
            id_selector = 'input[id="frmIlban.sg_uid"]'
            pw_selector = 'input[id="frmIlban.sg_pwd"]'
            btn_selector = 'input[id="frmIlban.pb_i_login"]'
            
            page.wait_for_selector(id_selector, timeout=15000)
            page.fill(id_selector, args.username)
            page.fill(pw_selector, password)
            page.click(btn_selector)
            
            # 대기 및 새로고침 (포털 구조상 필수)
            page.wait_for_timeout(4000)
            page.reload()
            page.wait_for_load_state("load")
            page.wait_for_timeout(2000)
            
            # 2. 통합정보시스템 진입
            sys_btn_selector = 'img[id="frmsystem_s.imgsys1"]'
            with context.expect_page() as new_page_info:
                clicked = wait_and_click_in_any_frame(page, sys_btn_selector, timeout_sec=15)
                if not clicked:
                    clicked = wait_and_click_in_any_frame(page, 'img[alt="통합정보시스템"]', timeout_sec=5)
                if not clicked:
                    raise RuntimeError("통합정보시스템 진입 버튼을 찾지 못했습니다.")
                    
            knuis_page = new_page_info.value
            knuis_page.wait_for_load_state("load")
            
            # 3. 메뉴 진입
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
                
            name, major, year, _ = parse_and_save_data(args.username, data_frame)
            print(f"포털 데이터 연동 성공: {name} ({major}, {year}학년)")
            browser.close()
            return 0
            
    except Exception as e:
        print(f"포털 연동 중 에러 발생: {e}", file=sys.stderr)
        return 1

if __name__ == "__main__":
    sys.exit(main())
