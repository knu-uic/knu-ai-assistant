"""Minimal online-counseling automation for the KNUIS Webcrea screen."""

from __future__ import annotations

import time

from playwright.sync_api import sync_playwright

from sync.common import DEFAULT_PORTAL_URL
from sync.knuis_sync import (
    find_frame_by_iframe_id,
    open_menu,
    wait_and_click_in_any_frame,
)

_MENU_ID = "1000000248"
_FRAME_ID = "WEESDV0060"
_TOPIC_COLUMNS = ("ONE", "TWO", "THREE", "FOUR")


def _has_system_button(page) -> bool:
    for frame in page.frames:
        for selector in ('img[id="frmsystem_s.imgsys1"]', 'img[alt="통합정보시스템"]'):
            try:
                if frame.locator(selector).count() > 0:
                    return True
            except Exception:
                continue
    return False


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

    deadline = time.time() + 20
    while time.time() < deadline:
        frame = find_frame_by_iframe_id(context, _FRAME_ID)
        if frame is not None:
            return page, frame
        page.wait_for_timeout(250)
    raise RuntimeError("상담신청 화면을 열지 못했습니다.")


def _text(frame, selector: str) -> str:
    try:
        return (frame.locator(selector).text_content() or "").strip()
    except Exception:
        return ""


def _topics(frame) -> list[str]:
    values = []
    for row in range(10):
        for column in _TOPIC_COLUMNS:
            value = _text(frame, f"#G2.{column}_NM{row}")
            if value:
                values.append(value)
    return values


def _select_topics(frame, topics: list[str]) -> None:
    available = {}
    for row in range(10):
        for column in _TOPIC_COLUMNS:
            label = _text(frame, f"#G2.{column}_NM{row}")
            if label:
                available[label] = f"#G2.{column}{row}"
    missing = [topic for topic in topics if topic not in available]
    if missing:
        raise RuntimeError(f"지원하지 않는 상담 주제입니다: {', '.join(missing)}")
    for topic in topics:
        frame.locator(available[topic]).check()


def prepare_online_counseling(student_id: str, storage_state: dict) -> dict:
    """Read only the default advisor and selectable topic labels."""
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        try:
            context = browser.new_context(storage_state=storage_state)
            _, frame = _open_counseling_page(context)
            advisor = _text(frame, "#G1.KOR_NM0") or _text(frame, "#G1.CNSLR_NM0")
            department = _text(frame, "#G1.DEPT_NM0") or _text(frame, "#G1.SUST_NM0")
            if not advisor:
                raise RuntimeError("기본 상담교수를 확인하지 못했습니다.")
            return {
                "success": True,
                "mode": "online",
                "advisor": advisor,
                "department": department or None,
                "topics": _topics(frame),
            }
        finally:
            browser.close()


def submit_online_counseling(
    student_id: str,
    storage_state: dict,
    title: str,
    content: str,
    topics: list[str],
) -> dict:
    """Save one online counseling request for the first (default) advisor."""
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        try:
            context = browser.new_context(storage_state=storage_state)
            page, frame = _open_counseling_page(context)
            advisor = _text(frame, "#G1.KOR_NM0") or _text(frame, "#G1.CNSLR_NM0")
            if not advisor:
                raise RuntimeError("기본 상담교수를 확인하지 못했습니다.")

            frame.locator("#G1.ON_CNSL0").click()
            _select_topics(frame, topics)
            frame.locator("#F1.CNSL_TTL_my_inputBox").fill(title)
            frame.locator("#F1.ASK_CTNT").click()
            page.keyboard.insert_text(content)
            frame.locator("#F_TOPMENU.BTN_SAVE").click()
            page.wait_for_timeout(1_000)
            return {
                "success": True,
                "submitted": True,
                "mode": "online",
                "advisor": advisor,
                "topics": topics,
            }
        finally:
            browser.close()
