"""Minimal online-counseling automation for the KNUIS Webcrea screen."""

from __future__ import annotations

import re
import time

from playwright.sync_api import Error as PlaywrightError, sync_playwright

from sync.common import DEFAULT_PORTAL_URL
from sync.knuis_sync import (
    find_frame_by_iframe_id,
    open_menu,
    wait_and_click_in_any_frame,
)
from sync.portal_auth import _browser_context_options

_MENU_ID = "1000000248"
_FRAME_ID = "WEESDV0060"
_INQUIRY_MENU_ID = "1000000249"
_INQUIRY_FRAME_ID = "WEESDV0050"
_SEARCH_FRAME_ID = "WEESDV0080"
_TOPIC_COLUMNS = ("ONE", "TWO", "THREE", "FOUR")
_ADVISOR_TABS = (
    ("#T1ItemRoot > label:nth-child(2) > div > div", "G1"),
    ("#T1ItemRoot > label:nth-child(8) > div > div", "G4"),
)
_ADVISOR_ROWS = 10
_SLOT_ROWS = 200


def _webcrea_id(value: str) -> str:
    return f'[id="{value}"]'


def _webcrea_click(frame, value: str) -> None:
    clicked = frame.evaluate(
        """id => {
            const element = document.getElementById(id);
            if (!element || typeof Webcrea?.OnCLICK !== 'function') return false;
            Webcrea.OnCLICK(element);
            return true;
        }""",
        value,
    )
    if not clicked:
        raise RuntimeError(f"상담 화면의 버튼을 찾지 못했습니다: {value}")


def _has_system_button(page) -> bool:
    for frame in page.frames:
        for selector in ('img[id="frmsystem_s.imgsys1"]', 'img[alt="통합정보시스템"]'):
            try:
                if frame.locator(selector).count() > 0:
                    return True
            except Exception:
                continue
    return False


def _find_counseling_form_frame(context):
    return _find_frame_with_id(context, "F_SRCH.BTN_SRCH")


def _find_advisor_search_frame(context):
    for page in context.pages:
        for frame in page.frames:
            try:
                if (
                    _SEARCH_FRAME_ID in frame.url
                    or any(frame.locator(selector).count() for selector, _ in _ADVISOR_TABS)
                ):
                    return frame
            except Exception:
                continue
    return None


def _find_inquiry_frame(context):
    frame = find_frame_by_iframe_id(context, _INQUIRY_FRAME_ID)
    try:
        return frame if frame and frame.locator(_webcrea_id("F_TOPMENU.BTN_SRCH")).count() else None
    except Exception:
        return None


def _find_frame_with_id(context, value: str):
    for page in context.pages:
        for frame in page.frames:
            try:
                if frame.locator(_webcrea_id(value)).count() > 0:
                    return frame
            except Exception:
                continue
    return None


def _has_portal_message(context, message: str) -> bool:
    for page in context.pages:
        for frame in page.frames:
            try:
                if message in (frame.locator("body").inner_text(timeout=250) or ""):
                    return True
            except Exception:
                continue
    return False


def _has_submitted_counseling(
    context, advisor: str, mode: str, date: str | None, title: str, content: str
) -> bool:
    """Confirm persistence from the portal's counseling inquiry grid."""
    if not date:
        return False
    page = next((page for page in context.pages if page.locator("#LeftFrame").count()), None)
    if page is None or not open_menu(page, _INQUIRY_MENU_ID, timeout_sec=10):
        return False
    deadline = time.time() + 10
    frame = None
    while time.time() < deadline:
        frame = _find_inquiry_frame(context)
        if frame is not None:
            try:
                if frame.evaluate(
                    "() => Boolean(globalThis._my_Page00_G1?.arrData?.CNSL_TTL)"
                ):
                    break
            except Exception:
                pass
        time.sleep(0.1)
    if frame is None:
        return False
    _webcrea_click(frame, "F_TOPMENU.BTN_SRCH")
    expected_date = _slot_date(date).replace("-", "")
    expected_mode = "G4B001" if mode == "visit" else "G4B002"
    deadline = time.time() + 10
    while time.time() < deadline:
        rows = frame.evaluate(
            """() => {
                const data = globalThis._my_Page00_G1?.arrData || {};
                return Object.fromEntries(Object.keys(data).map(key => [key, data[key]]));
            }"""
        )
        count = len(rows.get("CNSL_TTL", []))
        if any(
            rows.get("CNSL_TTL", [])[index] == title
            and rows.get("ASK_CTNT", [])[index] == content
            and rows.get("KOR_NM", [])[index] == _advisor_name(advisor)
            and rows.get("CNSL_DTTM", [])[index] == expected_date
            and rows.get("CNSL_TYPE_CD", [])[index] == expected_mode
            for index in range(count)
        ):
            return True
        time.sleep(0.2)
    return False


def _wait_for_frame(context, value: str, timeout_sec: float = 5):
    deadline = time.time() + timeout_sec
    while time.time() < deadline:
        frame = _find_frame_with_id(context, value)
        if frame is not None:
            return frame
        time.sleep(0.1)
    return None


def _counseling_frame_state(context) -> str:
    states = []
    for page in context.pages:
        for frame in page.frames:
            try:
                header = frame.locator(_webcrea_id("G1.Header")).count()
                search = frame.locator(_webcrea_id("F_SRCH.BTN_SRCH")).count()
                if header or search:
                    states.append(f"{frame.name or 'unnamed'}:header={header},search={search}")
            except Exception:
                continue
    return "; ".join(states) or "no G1 frame"


def _open_counseling_page(context):
    page = context.new_page()
    page.goto(DEFAULT_PORTAL_URL, wait_until="load", timeout=20_000)
    page.reload(wait_until="load", timeout=20_000)

    deadline = time.time() + 15
    while time.time() < deadline and page.locator("#LeftFrame").count() == 0:
        if _has_system_button(page):
            break
        page.wait_for_timeout(250)

    if page.locator("#LeftFrame").count() == 0:
        with context.expect_page() as next_page:
            clicked = wait_and_click_in_any_frame(
                page, 'img[id="frmsystem_s.imgsys1"]', timeout_sec=15
            )
            if not clicked:
                clicked = wait_and_click_in_any_frame(
                    page, 'img[alt="통합정보시스템"]', timeout_sec=5
                )
            if not clicked:
                raise RuntimeError("통합정보시스템 진입 버튼을 찾지 못했습니다.")
        page = next_page.value
        page.wait_for_load_state("load")

    def is_ready() -> bool:
        try:
            return page.evaluate("""() => {
                const w = document.querySelector('#LeftFrame')?.contentWindow;
                return Boolean(w?.Page00?.funcLeft?.fn_runFileMDI);
            }""")
        except Exception:
            return False

    deadline = time.time() + 30
    while time.time() < deadline:
        if is_ready():
            break
        page.wait_for_timeout(500)
    else:
        raise RuntimeError("통합정보시스템 세션이 만료되었습니다. 포털을 다시 연결해주세요.")

    if not open_menu(page, _MENU_ID, timeout_sec=10):
        raise RuntimeError("상담신청 메뉴를 열지 못했습니다.")

    deadline = time.time() + 60
    while time.time() < deadline:
        if find_frame_by_iframe_id(context, _FRAME_ID) is not None:
            break
        page.wait_for_timeout(250)
    else:
        raise RuntimeError("상담신청 화면을 열지 못했습니다.")

    page.wait_for_timeout(10_000)
    deadline = time.time() + 20
    while time.time() < deadline:
        frame = _find_counseling_form_frame(context)
        if frame is not None:
            return page, frame
        page.wait_for_timeout(250)
    raise RuntimeError(
        "상담신청 화면의 입력 폼을 찾지 못했습니다. "
        f"프레임 상태: {_counseling_frame_state(context)}"
    )


def _text(frame, selector: str) -> str:
    locator = frame.locator(selector)
    try:
        if locator.count() == 0:
            return ""
    except Exception:
        return ""
    for read in (locator.text_content, locator.input_value, lambda: locator.get_attribute("value")):
        try:
            value = (read() or "").strip()
            if value:
                return value
        except Exception:
            continue
    return ""


def _slot_date(value: str) -> str:
    value = str(value).strip()
    if value.isdigit() and len(value) == 8:
        return f"{value[:4]}-{value[4:6]}-{value[6:]}"
    match = re.fullmatch(r"(\d{4})\D+(\d{1,2})\D+(\d{1,2})\D*", value)
    return f"{match.group(1)}-{int(match.group(2)):02d}-{int(match.group(3)):02d}" if match else value


def _slot_time(value: str) -> str:
    value = str(value).strip()
    match = re.fullmatch(r"(\d{1,2}:\d{2})\s*~\s*(\d{1,2}:\d{2})", value)
    return f"{match.group(1)} ~ {match.group(2)}" if match else value


def _topics(frame) -> list[str]:
    values = []
    for row in range(10):
        for column in _TOPIC_COLUMNS:
            value = _text(frame, _webcrea_id(f"G2.{column}_NM{row}"))
            if value:
                values.append(value)
    return values


def _advisors(frame, group: str = "G1") -> list[dict]:
    advisors = []
    for row in range(_ADVISOR_ROWS):
        name = _text(frame, _webcrea_id(f"{group}.KOR_NM{row}"))
        if not name:
            continue
        advisors.append({
            "name": name,
            "department": _text(frame, _webcrea_id(f"{group}.DEPT_NM{row}")) or None,
            "row": row,
        })
    return advisors


def _advisor_entries(frame) -> list[dict]:
    entries = []
    for selector, group in _ADVISOR_TABS:
        tab = frame.locator(selector)
        if tab.count() == 0:
            continue
        tab.click()
        entries.extend({**advisor, "group": group} for advisor in _advisors(frame, group))
    return entries


def _slots(frame) -> list[dict]:
    try:
        slots = frame.evaluate(
            """() => {
                const grid = Object.values(globalThis).find(value =>
                    value?.arrRows && value?.arrData && value?.divPos === 'G3'
                );
                if (!grid) return null;
                const { arrRows, arrData } = grid;
                return arrRows.map((_, row) => ({
                    date: arrData.RESER_DT?.[row] || '',
                    time: arrData.TM?.[row] || '',
                    row,
                }));
            }"""
        )
        if slots is not None:
            return [
                {**slot, "date": _slot_date(slot["date"])}
                for slot in slots
                if slot["date"] and slot["time"]
            ]
    except Exception:
        pass

    slots = []
    for row in range(_SLOT_ROWS):
        date = _text(frame, _webcrea_id(f"G3.RESER_DT{row}"))
        time_text = _text(frame, _webcrea_id(f"G3.TM{row}"))
        if date and time_text:
            slots.append({"date": _slot_date(date), "time": time_text, "row": row})
    return slots


def _select_advisor(frame, advisor: str) -> None:
    matches = [item for item in _advisor_entries(frame) if item["name"] == advisor]
    if len(matches) != 1:
        raise RuntimeError(f"선택한 상담교수를 찾지 못했습니다: {advisor}")
    for selector, group in _ADVISOR_TABS:
        if group == matches[0]["group"]:
            frame.locator(selector).click()
            break
    try:
        frame.locator(_webcrea_id(f"{matches[0]['group']}.KOR_NM{matches[0]['row']}")).dblclick()
    except PlaywrightError as exc:
        # KNUIS closes the search popup synchronously after a successful double click.
        if "Target page, context or browser has been closed" not in str(exc):
            raise


def _advisor_name(value: str) -> str:
    return value.strip().removesuffix("교수님").removesuffix("교수").strip()


def _select_mode(frame, mode: str, advisor_row: int = 0) -> None:
    if mode not in {"online", "visit"}:
        raise RuntimeError("상담 방식은 online 또는 visit이어야 합니다.")
    _webcrea_click(frame, f"G1.{'ON' if mode == 'online' else 'OFF'}_CNSL{advisor_row}")


def _select_slot(frame, date: str, time_text: str) -> None:
    date, time_text = _slot_date(date), _slot_time(time_text)
    matches = [item for item in _slots(frame) if item["date"] == date and item["time"] == time_text]
    if len(matches) != 1:
        raise RuntimeError(f"선택한 상담 일시를 찾지 못했습니다: {date} {time_text}")
    row = matches[0]["row"]
    try:
        frame.evaluate(
            """row => {
                const grid = Object.values(globalThis).find(value => value?.divPos === 'G3');
                grid?.SetRowNo?.(row);
            }""",
            row,
        )
    except Exception:
        pass
    _webcrea_click(frame, f"G3.OFF_CNSL{row}")


def _select_topics(frame, topics: list[str]) -> None:
    available = {}
    for row in range(10):
        for column in _TOPIC_COLUMNS:
            label = _text(frame, _webcrea_id(f"G2.{column}_NM{row}"))
            if label:
                available[label] = f"G2.{column}{row}"
    missing = [topic for topic in topics if topic not in available]
    if missing:
        raise RuntimeError(f"지원하지 않는 상담 주제입니다: {', '.join(missing)}")
    for topic in topics:
        _webcrea_click(frame, available[topic])


def _open_advisor_search(context, frame):
    _webcrea_click(frame, "F_SRCH.BTN_SRCH")
    deadline = time.time() + 15
    while time.time() < deadline:
        search_frame = _find_advisor_search_frame(context)
        if search_frame is not None:
            if _advisor_entries(search_frame):
                return search_frame
        time.sleep(0.2)
    raise RuntimeError("상담교수 검색 창을 열지 못했습니다.")


def _choose_advisor(context, frame, advisor: str, search_frame=None) -> int:
    advisor = _advisor_name(advisor)
    before = _advisors(frame)
    search_frame = search_frame or _open_advisor_search(context, frame)
    _select_advisor(search_frame, advisor)
    deadline = time.time() + 5
    while time.time() < deadline:
        selected = [item for item in _advisors(frame) if item["name"] == advisor]
        added = [item for item in selected if item not in before]
        if len(added) == 1:
            return added[0]["row"]
        if len(selected) == 1:
            return selected[0]["row"]
        time.sleep(0.1)
    raise RuntimeError(f"상담교수 선택을 확인하지 못했습니다: {advisor}")


def _fill_title_and_content(frame, page, title: str, content: str) -> None:
    # Webcrea keeps the table-cell wrapper hidden while its generated input is visible.
    title_field = frame.locator(_webcrea_id("F1.CNSL_TTL_my_inputBox"))
    if title_field.count() == 0:
        title_field = frame.locator(_webcrea_id("F1.CNSL_TTL"))
    title_field.fill(title)
    content_field = frame.locator("#F1 > table > tbody > tr:nth-child(7) > td.mi75 > div > div")
    content_field.click()
    page.keyboard.insert_text(content)


def prepare_online_counseling(
    student_id: str,
    storage_state: dict,
    advisor: str | None = None,
    mode: str = "online",
) -> dict:
    """Read advisors and topics; visit mode additionally reads selectable visit slots."""
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        try:
            context = browser.new_context(
                storage_state=storage_state, **_browser_context_options()
            )
            page, frame = _open_counseling_page(context)
            search_frame = _open_advisor_search(context, frame)
            advisors = _advisor_entries(search_frame)
            if not advisors:
                raise RuntimeError("상담교수를 확인하지 못했습니다.")
            if advisor is not None:
                advisor_row = _choose_advisor(context, frame, advisor, search_frame)
                _select_mode(frame, mode, advisor_row)
                page.wait_for_timeout(500)
                slots = [
                    {"date": slot["date"], "time": slot["time"]}
                    for slot in _slots(frame)
                ] if mode == "visit" else []
            else:
                slots = []
            result = {
                "success": True,
                "mode": mode,
                "advisors": [
                    {key: value for key, value in item.items() if key not in {"row", "group"}}
                    for item in advisors
                ],
                "topics": _topics(frame),
            }
            if mode == "visit":
                result["slots"] = slots
                result["slot_count"] = len(slots)
            return result
        finally:
            browser.close()


def submit_online_counseling(
    student_id: str,
    storage_state: dict,
    advisor: str,
    mode: str,
    date: str | None,
    time_text: str | None,
    title: str,
    content: str,
    topics: list[str],
) -> dict:
    """Save one selected online or visit counseling request."""
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        try:
            context = browser.new_context(
                storage_state=storage_state, **_browser_context_options()
            )
            page, frame = _open_counseling_page(context)
            advisor_row = _choose_advisor(context, frame, advisor)
            _select_mode(frame, mode, advisor_row)
            page.wait_for_timeout(500)
            if mode == "visit":
                if not date or not time_text:
                    raise RuntimeError("방문 상담은 날짜와 시간을 선택해야 합니다.")
                _select_slot(frame, date, time_text)
                page.wait_for_timeout(500)
            elif mode != "online":
                raise RuntimeError("상담 방식은 online 또는 visit이어야 합니다.")
            _fill_title_and_content(frame, page, title, content)
            _select_topics(frame, topics)
            page.wait_for_timeout(500)
            save_frame = _find_frame_with_id(context, "F_TOPMENU.BTN_SAVE")
            if save_frame is None:
                raise RuntimeError("상담신청 저장 버튼을 찾지 못했습니다.")
            _webcrea_click(save_frame, "F_TOPMENU.BTN_SAVE")
            confirm_frame = _wait_for_frame(context, "frmBtn5.btnOk")
            if confirm_frame is None:
                raise RuntimeError("상담신청 확인창을 열지 못했습니다.")
            _webcrea_click(confirm_frame, "frmBtn5.btnOk")

            if not _has_submitted_counseling(
                context, advisor, mode, date, title, content
            ):
                raise RuntimeError("포털에서 상담신청 완료를 확인하지 못했습니다.")
            return {
                "success": True,
                "submitted": True,
                "mode": mode,
                "advisor": advisor,
                "date": date,
                "time": time_text,
                "topics": topics,
            }
        finally:
            browser.close()
