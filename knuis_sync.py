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

def _find_frame_by_url(page, substr):
    """page.frames 순회하여 URL에 substr이 포함된 첫 Frame을 반환. 없으면 None."""
    for frame in page.frames:
        try:
            if substr in frame.url:
                return frame
        except Exception:
            continue
    return None


def wait_for_frame_by_url(page, substr, timeout_sec=30):
    """URL substring에 해당하는 frame이 page.frames에 등장할 때까지 polling. 없으면 None."""
    deadline = time.time() + timeout_sec
    while time.time() < deadline:
        f = _find_frame_by_url(page, substr)
        if f is not None:
            return f
        time.sleep(0.5)
    return None


def wait_for_menu_ready(page, timeout_sec=60):
    """LeftFrame 프레임이 등장하고 '메뉴 항목(라이브값)이 채워질 때까지' 대기.
    통합정보시스템 진입 직후엔 프레임은 떠도 메뉴 데이터 로드가 늦어, URL 등장만 보고
    클릭하면 빈 메뉴를 눌러 실패한다. 실제 항목이 생길 때까지 polling."""
    try:
        page.screenshot(timeout=3000)
    except Exception:
        pass
    start = time.time()
    deadline = start + timeout_sec
    while time.time() < deadline:
        frame = page.frame(name="LeftFrame")
        if frame is not None:
            try:
                inputs = frame.locator('#listMenu input[id^="listMenu.menu_nm"]')
                if inputs.count() > 0:
                    val = inputs.first.evaluate("el => el.value || el.title || el.getAttribute('orgtitle') || ''")
                    if val.strip():
                        return frame
            except Exception:
                pass
        time.sleep(1)
    return None


def click_left_menu(page, name, timeout_ms=1500, wait_frame_sec=30) -> bool:
    """좌측 메뉴 트리(가상화 DOM)에서 다양한 scroll 위치를 훑으며 매칭+클릭.
    카테고리별 selector 다층: role=textbox+name → input[title=] → input[orgtitle=] → input[title*=]."""
    try:
        page.screenshot(timeout=3000)
    except Exception:
        pass
    menu_frame = None
    deadline = time.time() + wait_frame_sec
    while time.time() < deadline:
        menu_frame = page.frame(name="LeftFrame")
        if menu_frame is not None:
            break
        time.sleep(0.5)
    if menu_frame is None:
        print(f"[click_left_menu] LeftFrame을 {wait_frame_sec}초 안에 찾지 못함 (요청: '{name}')", file=sys.stderr, flush=True)
        return False

    def selectors():
        return [
            ("role:textbox", lambda: menu_frame.get_by_role("textbox", name=name).first),
            ("input[title=]", lambda: menu_frame.locator(f'input[title="{name}"]').first),
            ("input[orgtitle=]", lambda: menu_frame.locator(f'input[orgtitle="{name}"]').first),
            ("input[title*=]", lambda: menu_frame.locator(f'input[title*="{name}"]').first),
        ]

    def _click_by_live_value():
        """Webcrea 메뉴는 라벨 텍스트를 title/value '속성'이 아니라 라이브 JS property(.value)에
        바인딩한다(특히 자식 메뉴는 속성이 빈 문자열). 라이브값으로 매칭해 element id로 클릭."""
        try:
            el_id = menu_frame.evaluate("""(name) => {
                const norm = s => (s || '').replace(/\\s+/g, '').trim();
                const target = norm(name);
                const inputs = Array.from(document.querySelectorAll('#listMenu input[id^="listMenu.menu_nm"]'));
                const liveOf = inp => norm(inp.value) || norm(inp.title) || norm(inp.getAttribute('orgtitle'));
                for (const inp of inputs) if (liveOf(inp) === target) return inp.id;
                for (const inp of inputs) { const v = liveOf(inp); if (v && v.indexOf(target) !== -1) return inp.id; }
                return null;
            }""", name)
        except Exception:
            el_id = None
        if not el_id:
            return False
        try:
            # 자식 행은 <div>와 <input>이 같은 id를 공유하므로 input으로 한정.
            menu_frame.locator(f'input[id="{el_id}"]').click(timeout=timeout_ms)
            print(f"[click_left_menu] '{name}' 클릭 성공 (live-value @ {el_id})", flush=True)
            return True
        except Exception:
            return False

    def _try_click(scroll_label):
        if _click_by_live_value():
            return True
        for label, fn in selectors():
            try:
                loc = fn()
                loc.click(timeout=timeout_ms)
                print(f"[click_left_menu] '{name}' 클릭 성공 ({label} @ {scroll_label})", flush=True)
                return True
            except Exception:
                continue
        return False

    dims = None
    try:
        dims = menu_frame.evaluate("""() => {
            const el = document.getElementById('listMenu');
            if (!el) return null;
            return { sh: el.scrollHeight, ch: el.clientHeight };
        }""")
    except Exception:
        pass

    if dims and dims.get("sh") and dims.get("ch"):
        step = max(int(dims["ch"] * 0.5), 50)
        positions = list(range(0, int(dims["sh"]) + step, step))
    else:
        positions = [0, 100, 300, 600, 900, 1200, 1500]
    positions = [0] + positions + [0]

    seen = set()
    for pos in positions:
        if pos in seen:
            continue
        seen.add(pos)
        try:
            menu_frame.evaluate(f"() => {{ const el = document.getElementById('listMenu'); if (el) el.scrollTop = {pos}; }}")
        except Exception:
            pass
        time.sleep(0.3)
        if _try_click(f"scrollTop={pos}"):
            return True

    titles = []
    try:
        titles = menu_frame.locator('input[title]:not([title=""])').evaluate_all("els => els.map(e => e.getAttribute('title'))")
    except Exception:
        pass
    print(f"[click_left_menu] '{name}' 모든 fallback/scroll 실패. 마지막 dump title: {titles[:40]}", file=sys.stderr, flush=True)
    return False


def find_menu_tree_frame(page, timeout_sec=10):
    """좌측 메뉴 트리(Webcrea leftMenuS) frame을 식별해 반환. 못 찾으면 None.
    1차: frame URL에 'leftMenu' 포함 / 2차: frame 내부에 id='listMenu' element 존재."""
    start_time = time.time()
    while time.time() - start_time < timeout_sec:
        for frame in page.frames:
            try:
                if "leftMenu" in frame.url:
                    return frame
            except Exception:
                continue
        for frame in page.frames:
            try:
                if frame.locator('#listMenu').count() > 0:
                    return frame
            except Exception:
                continue
        time.sleep(0.5)
    return None


def _reset_menu_scroll(menu_frame):
    """가상화 트리 대응: #listMenu 컨테이너 scrollTop을 0으로 리셋. 실패 시 무시."""
    try:
        menu_frame.evaluate("() => { const el = document.getElementById('listMenu'); if (el) el.scrollTop = 0; }")
    except Exception:
        pass


def _scroll_menu_down(menu_frame, step_ratio=0.5) -> bool:
    """메뉴 트리를 한 단계 아래로 스크롤. 더 내려갈 곳 없으면 False."""
    try:
        return bool(menu_frame.evaluate("""r => {
            const el = document.getElementById('listMenu');
            if (!el) return false;
            const before = el.scrollTop;
            const max = el.scrollHeight - el.clientHeight;
            const target = Math.min(before + el.clientHeight * r, max);
            el.scrollTop = target;
            return el.scrollTop > before;
        }""", step_ratio))
    except Exception:
        return False


def click_menu_by_title(page, menu_title, timeout_sec=15) -> bool:
    """좌측 메뉴 트리 frame(가상화 가능성)에서 title 정확 매칭 input 클릭.
    스크롤을 위→아래로 점진 이동하며 매칭 시도. 발견 시 scrollIntoView + click."""
    print(f"[click_menu_by_title] '{menu_title}' 메뉴 클릭 시도 중...", flush=True)
    menu_frame = find_menu_tree_frame(page, timeout_sec=timeout_sec)
    if menu_frame is None:
        print("[click_menu_by_title] 메뉴 트리 frame(leftMenu/#listMenu)을 찾지 못함.", file=sys.stderr, flush=True)
        return False
    print(f"[click_menu_by_title] 메뉴 트리 frame: {menu_frame.url}", flush=True)

    exact_selector = f'input[title="{menu_title}"]'
    deadline = time.time() + timeout_sec

    _reset_menu_scroll(menu_frame)
    time.sleep(0.3)

    def _try_match():
        try:
            locator = menu_frame.locator(exact_selector)
            if locator.count() > 0:
                locator.first.scroll_into_view_if_needed()
                try:
                    locator.first.click(timeout=2000)
                except Exception:
                    locator.first.evaluate("el => el.click()")
                return True
        except Exception:
            return False
        return False

    while time.time() < deadline:
        if _try_match():
            print(f"[click_menu_by_title] 매칭/클릭 성공: '{menu_title}'", flush=True)
            return True
        if not _scroll_menu_down(menu_frame):
            break
        time.sleep(0.3)

    _reset_menu_scroll(menu_frame)
    time.sleep(0.3)
    if _try_match():
        print(f"[click_menu_by_title] (스크롤 리셋 후) 매칭/클릭 성공: '{menu_title}'", flush=True)
        return True

    titles = []
    try:
        titles = menu_frame.locator('#listMenu input[title]:not([title=""])').evaluate_all("els => els.map(e => e.getAttribute('title'))")
    except Exception:
        pass
    print(f"[click_menu_by_title] '{menu_title}' 매칭 실패. 현재 DOM title 목록(비공백만): {titles}", file=sys.stderr, flush=True)
    return False


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


def parse_webcrea_grid(frame, grid_id, code_map) -> dict | None:
    """Webcrea 그리드(div#<grid_id>)를 {columns, rows} 구조로 파싱.
    - columns: 헤더 행 td의 span[title](화면 표시 라벨)
    - rows: tr[id^="<grid_id>.Data"] 각 td. Combo Box 셀은 input[code]→code_map 변환,
      일반 셀은 value 속성(없으면 innerText)."""
    try:
        return frame.evaluate("""([gid, codeMap]) => {
            const container = document.getElementById(gid);
            if (!container) return null;
            // 헤더 행이 여러 개일 수 있어(예: G2는 '<학기성적>' 버튼 행 + 컬럼 행)
            // 라벨(span title)이 가장 많은 행을 컬럼 헤더로 선택.
            let columns = [];
            container.querySelectorAll('tr[id="' + gid + '.Header"]').forEach(tr => {
                const cols = Array.from(tr.querySelectorAll('td')).map(td => {
                    const sp = td.querySelector('span');
                    return sp ? (sp.getAttribute('title') || sp.innerText || '').trim() : '';
                });
                if (cols.filter(c => c).length > columns.filter(c => c).length) columns = cols;
            });
            const rows = [];
            container.querySelectorAll('tr[id^="' + gid + '.Data"]').forEach(tr => {
                const cells = Array.from(tr.querySelectorAll('td')).map(td => {
                    const combo = td.querySelector('input[codeobj="code"]');
                    if (combo) return codeMap[combo.getAttribute('code')] || '';
                    const v = td.getAttribute('value');
                    return (v != null ? v : td.innerText).trim();
                });
                rows.push(cells);
            });
            return { columns, rows };
        }""", [grid_id, code_map])
    except Exception:
        return None


def collect_webcrea_grid(frame, grid_id, code_map, max_loops=40) -> dict | None:
    """가상화 그리드 대응: 세로 스크롤(휠 + 스크롤바 down arrow)을 반복하며
    보이는 행을 rowno 기준으로 누적 수집. 더 이상 새 행이 안 나오면 종료.
    Webcrea 그리드는 화면에 보이는 행만 DOM에 렌더하므로 단발 파싱은 일부만 긁힘."""
    snap_js = """([gid, codeMap]) => {
        const container = document.getElementById(gid);
        if (!container) return null;
        let columns = [];
        container.querySelectorAll('tr[id="' + gid + '.Header"]').forEach(tr => {
            const cols = Array.from(tr.querySelectorAll('td')).map(td => {
                const sp = td.querySelector('span');
                return sp ? (sp.getAttribute('title') || sp.innerText || '').trim() : '';
            });
            if (cols.filter(c => c).length > columns.filter(c => c).length) columns = cols;
        });
        const rows = [];
        container.querySelectorAll('tr[id^="' + gid + '.Data"]').forEach(tr => {
            const rno = tr.getAttribute('rowno');
            const cells = Array.from(tr.querySelectorAll('td')).map(td => {
                const combo = td.querySelector('input[codeobj="code"]');
                if (combo) return codeMap[combo.getAttribute('code')] || '';
                const v = td.getAttribute('value');
                return (v != null ? v : td.innerText).trim();
            });
            rows.push([rno, cells]);
        });
        return { columns, rows };
    }"""
    page = frame.page
    seen = {}
    columns = []
    try:
        for _ in range(max_loops):
            snap = frame.evaluate(snap_js, [grid_id, code_map])
            if not snap:
                return None
            if snap["columns"]:
                columns = snap["columns"]
            new = 0
            for rno, cells in snap["rows"]:
                key = rno if rno is not None else str(len(seen))
                filled = sum(1 for c in cells if c.strip())
                prev = seen.get(key)
                if prev is None:
                    seen[key] = cells
                    new += 1
                elif filled > sum(1 for c in prev if c.strip()):
                    # 부분 렌더된 스냅샷을 더 채워진 것으로 갱신.
                    seen[key] = cells
            # 그리드 위에서 실제 마우스 휠을 굴려 가상화 다음 행을 렌더(synthetic 이벤트는 Webcrea가 무시).
            try:
                box = frame.locator(f'[id="{grid_id}"]').first.bounding_box()
                if box:
                    page.mouse.move(box["x"] + box["width"] / 2, box["y"] + box["height"] / 2)
                    page.mouse.wheel(0, 400)
            except Exception:
                pass
            time.sleep(0.3)
            if new == 0:
                break
    except Exception:
        if not seen:
            return None

    def _k(x):
        try:
            return int(x)
        except (TypeError, ValueError):
            return 1 << 30
    # 가상화 끝까지 스크롤 시 딸려오는 완전 빈 행(placeholder) 제외.
    ordered = [seen[k] for k in sorted(seen, key=_k) if any(c.strip() for c in seen[k])]
    return {"columns": columns, "rows": ordered}


def parse_webcrea_keyvalue(frame, container_id) -> list[list[str]] | None:
    """라벨/값 쌍으로 배치된 Webcrea 표(성적분포 F1 총괄)를 [[라벨, 값], ...]로 파싱."""
    try:
        return frame.evaluate("""(cid) => {
            const c = document.getElementById(cid);
            if (!c) return null;
            const tds = Array.from(c.querySelectorAll('td'));
            const pairs = [];
            for (let i = 0; i < tds.length; i++) {
                const td = tds[i];
                const sp = td.querySelector('span');
                const v = td.getAttribute('value');
                if (sp && v == null) {
                    const next = tds[i + 1];
                    const val = next ? ((next.getAttribute('value') != null ? next.getAttribute('value') : next.innerText) || '').trim() : '';
                    pairs.push([sp.innerText.trim().replace(/\\s+/g, ' '), val]);
                    i++;
                }
            }
            return pairs;
        }""", container_id)
    except Exception:
        return None


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


GRADE_DIST_GRIDS = {"G1": "학기별 성적"}


def parse_grade_distribution(context) -> dict | None:
    """WHHSJV0275(나의성적분포): G1(학기별 성적) 그리드 + F1(전체 요약)을 구조화 파싱."""
    frame = find_frame_by_url_substr(context, "WHHSJV0275")
    if frame is None:
        print("[grade_distribution] WHHSJV0275 프레임을 찾지 못했습니다.", file=sys.stderr, flush=True)
        return None
    code_map = _build_code_map(frame)
    grids = {}
    for gid, title in GRADE_DIST_GRIDS.items():
        g = collect_webcrea_grid(frame, gid, code_map)
        if g and g.get("rows"):
            g["title"] = title
            grids[gid] = g
    summary = parse_webcrea_keyvalue(frame, "F1")
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


CUMULATIVE_GRIDS = {"G1": "과목별 성적", "G2": "학기별 성적", "G3": "이수구분별 학점"}


def parse_cumulative_grades(context) -> dict | None:
    """WHHSJV0270(누적성적조회): G1(과목별)·G2(학기별)·G3(이수구분별) 그리드를 구조화 파싱.
    등급(GRD_CD)·이수구분(POBT_FG_CD)·재수강(RETLSN_YN)·학사경고(BCH_WARN_YN)는 Combo이라 code_map으로 디코딩됨."""
    frame = find_frame_by_url_substr(context, "WHHSJV0270")
    if frame is None:
        print("[cumulative_grades] WHHSJV0270 프레임을 찾지 못했습니다.", file=sys.stderr, flush=True)
        return None
    code_map = _build_code_map(frame)
    grids = {}
    for gid, title in CUMULATIVE_GRIDS.items():
        g = collect_webcrea_grid(frame, gid, code_map)
        if g and g.get("rows"):
            g["title"] = title
            grids[gid] = g
    if not grids:
        print("[cumulative_grades] 파싱 결과가 비어 있습니다.", file=sys.stderr, flush=True)
        return None
    return {"frame_url": frame.url, "grids": grids}


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
            
            # 3. 시간표 (LeftFrame role textbox 기반)
            #    졸업 메뉴 진입 시 트리가 program path만 남도록 좁혀지므로 시간표/성적/누적 먼저 처리.
            #    먼저 leftMenu frame이 로드될 때까지 대기 (loginS.jsp → 메뉴+MDI 페이지 전환 후).
            print("[3/8] leftMenu 메뉴 항목 로드 대기 중 (최대 120초)...", flush=True)
            menu_frame_ready = wait_for_menu_ready(knuis_page, timeout_sec=120)
            if menu_frame_ready is None:
                print("[3/8] leftMenu 메뉴 항목이 180초 안에 채워지지 않음.", file=sys.stderr, flush=True)
            else:
                print(f"[3/8] leftMenu 메뉴 로드 확인: {menu_frame_ready.url}", flush=True)
            timetable_json = None
            try:
                print("[3/8] 시간표 조회 시작 (LeftFrame role 경유)...", flush=True)
                click_left_menu(knuis_page, "수업 · 수강")
                knuis_page.wait_for_timeout(1500)
                click_left_menu(knuis_page, "시간표조회")
                knuis_page.wait_for_timeout(3000)
                timetable_json = parse_timetable_data(context)
                print(f"[3/8] 시간표 파싱 완료 (테이블 수: {len(timetable_json) if timetable_json else 0})", flush=True)
            except Exception as te:
                print(f"시간표 연동 중 오류 발생: {te}", file=sys.stderr, flush=True)

            # 4. 나의 성적분포
            grade_distribution_json = None
            try:
                print("[4/8] 나의 성적분포 조회 시작...", flush=True)
                click_left_menu(knuis_page, "성적")
                knuis_page.wait_for_timeout(1500)
                # 누적성적조회와 동일하게 '성적' 직속 자식인 '나의성적분포'를 바로 클릭.
                # 클릭 시 WHHSKV 상위 shell이 먼저 뜨고 그 안 HtmlAddrFrame에 WHHSJV0275가 늦게
                # 로드되므로 settle 대기 후 더 길게(30s) 폴링.
                click_left_menu(knuis_page, "나의성적분포")
                knuis_page.wait_for_timeout(3000)
                wait_for_grid_rows(context, "WHHSJV0275", "G1", timeout_sec=30)
                grade_distribution_json = parse_grade_distribution(context)
                print(f"[4/8] 나의 성적분포 파싱 완료 (그리드 수: {len(grade_distribution_json['grids']) if grade_distribution_json else 0})", flush=True)
            except Exception as ge:
                print(f"나의 성적분포 연동 중 오류 발생: {ge}", file=sys.stderr, flush=True)

            # 5. 누적성적조회(학부생) ('전체' 학기 강제 선택)
            cumulative_grades_json = None
            try:
                print("[5/8] 누적성적조회 시작...", flush=True)
                click_left_menu(knuis_page, "누적성적조회(학부생)")
                knuis_page.wait_for_timeout(3000)
                select_semester_all(knuis_page)
                knuis_page.wait_for_timeout(500)
                wait_for_grid_rows(context, "WHHSJV0270", "G1", timeout_sec=20)
                cumulative_grades_json = parse_cumulative_grades(context)
                print(f"[5/8] 누적성적조회 파싱 완료 (그리드 수: {len(cumulative_grades_json['grids']) if cumulative_grades_json else 0})", flush=True)
            except Exception as ce:
                print(f"누적성적조회 연동 중 오류 발생: {ce}", file=sys.stderr, flush=True)

            # 6. 졸업사전예고: 학적(이름/학과/학년) + 졸업 취득학점.
            #    이 단계가 메뉴 트리를 좁히므로 가장 마지막에 수행.
            # 졸업사전예고 실패가 시간표·성적 결과 출력/저장을 막지 않도록 비치명적 처리.
            name, major, year, grad_json = None, None, None, None
            try:
                print("[6/8] 졸업사전예고 메뉴 탐색 중...", flush=True)
                # 시간표·성적과 동일하게 live-value 매칭으로 클릭(하드코딩 id 폐기).
                # 자식 라벨 정확값('졸업사전예고(학생)')을 몰라도 contains 매칭으로 잡히게 짧게 전달.
                click_left_menu(knuis_page, "졸업")
                knuis_page.wait_for_timeout(1500)
                clicked = click_left_menu(knuis_page, "졸업사전예고")
                if not clicked:
                    raise RuntimeError("졸업사전예고(학생) 메뉴를 찾지 못했습니다.")
                knuis_page.wait_for_timeout(3000)

                confirm_selector = 'input[id="Form2.pb1"]'
                clicked = wait_and_click_in_any_frame(knuis_page, confirm_selector, timeout_sec=20)
                if clicked:
                    knuis_page.wait_for_timeout(5000)
                else:
                    raise RuntimeError("확인 조회 버튼을 찾지 못했습니다.")

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
