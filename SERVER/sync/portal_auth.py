"""Fast KNU portal credential verification for Codmes plugin login."""

from __future__ import annotations

import time
import tempfile
from pathlib import Path
from threading import Lock

from sync.common import DEFAULT_PORTAL_URL

_syncing_student_ids: set[str] = set()
_sync_stage_by_student: dict[str, str] = {}
_lms_error_by_student: dict[str, str] = {}
_syncing_lock = Lock()


def mark_portal_sync_started(student_id: str) -> None:
    with _syncing_lock:
        _syncing_student_ids.add(student_id)
        _sync_stage_by_student[student_id] = "학교 데이터 동기화 준비 중"
        _lms_error_by_student.pop(student_id, None)


def is_portal_syncing(student_id: str) -> bool:
    with _syncing_lock:
        return student_id in _syncing_student_ids


def portal_sync_status(student_id: str) -> dict:
    with _syncing_lock:
        return {
            "syncing": student_id in _syncing_student_ids,
            "stage": _sync_stage_by_student.get(student_id),
            "lms_error": _lms_error_by_student.get(student_id),
        }


def _set_sync_stage(student_id: str, stage: str) -> None:
    with _syncing_lock:
        _sync_stage_by_student[student_id] = stage


def _finish_sync(student_id: str) -> None:
    with _syncing_lock:
        _syncing_student_ids.discard(student_id)
        _sync_stage_by_student.pop(student_id, None)


def _set_lms_error(student_id: str, error: Exception | str) -> None:
    message = str(error).strip() or "알 수 없는 오류"
    with _syncing_lock:
        _lms_error_by_student[student_id] = message[:300]


def _browser_context_options() -> dict:
    return {
        "viewport": {"width": 1280, "height": 800},
        "user_agent": (
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/120.0.0.0 Safari/537.36"
        ),
    }


def _has_visible_system_button(page) -> bool:
    selectors = (
        'img[id="frmsystem_s.imgsys1"]',
        'img[alt="통합정보시스템"]',
    )
    for frame in page.frames:
        for selector in selectors:
            try:
                locator = frame.locator(selector)
                if locator.count() > 0 and locator.first.is_visible():
                    return True
            except Exception:
                continue
    return False


def authenticate_portal(student_id: str, password: str) -> dict | None:
    """Verify university SSO and return its temporary browser session state."""
    if not student_id.strip() or not password:
        return None

    from playwright.sync_api import sync_playwright

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        try:
            context = browser.new_context(**_browser_context_options())
            page = context.new_page()
            rejected = False

            def handle_dialog(dialog) -> None:
                nonlocal rejected
                message = dialog.message.lower()
                rejected = any(
                    keyword in message
                    for keyword in ("비밀번호", "아이디", "로그인", "invalid", "password")
                )
                dialog.accept()

            page.on("dialog", handle_dialog)
            page.goto(DEFAULT_PORTAL_URL, wait_until="load", timeout=15_000)
            page.wait_for_selector(
                'input[id="frmIlban.sg_uid"]',
                timeout=10_000,
            )
            page.fill('input[id="frmIlban.sg_uid"]', student_id.strip())
            page.fill('input[id="frmIlban.sg_pwd"]', password)
            page.click('input[id="frmIlban.pb_i_login"]')

            deadline = time.monotonic() + 15
            reloaded = False
            while time.monotonic() < deadline:
                if rejected:
                    return None
                if _has_visible_system_button(page):
                    return context.storage_state()
                if not reloaded and time.monotonic() + 10 < deadline:
                    page.wait_for_timeout(4_000)
                    page.reload(wait_until="load", timeout=15_000)
                    reloaded = True
                    continue
                page.wait_for_timeout(500)
            return None
        finally:
            browser.close()


def verify_portal_credentials(student_id: str, password: str) -> bool:
    """Compatibility wrapper used by focused authentication tests."""
    return authenticate_portal(student_id, password) is not None


def sync_portal_data(student_id: str, storage_state: dict) -> dict:
    """Reuse the verified SSO session to sync all supported KNUIS data."""
    from sync.knuis_sync import run_portal_sync

    mark_portal_sync_started(student_id)
    try:
        return run_portal_sync(
            student_id,
            storage_state=storage_state,
            on_step=lambda stage: _set_sync_stage(student_id, stage),
        )
    finally:
        _finish_sync(student_id)


def sync_lms_data(student_id: str, password: str) -> dict:
    """Create a temporary LMS session, sync Canvas/LearningX, then discard it."""
    from sync.lms_login import login_with_credentials
    from sync.lms_sync import run_lms_sync

    with tempfile.TemporaryDirectory() as tmp:
        state_path = Path(tmp) / "lms_storage_state.json"
        _set_sync_stage(student_id, "LMS 로그인 중")
        login_with_credentials(
            student_id,
            password,
            state=str(state_path),
            debug_dir=str(Path(tmp) / "debug"),
            generate_access_token=False,
        )
        return run_lms_sync(
            student_id,
            state_path=state_path,
            on_step=lambda stage: _set_sync_stage(student_id, stage),
        )


def sync_university_data(
    student_id: str,
    storage_state: dict,
    password: str,
) -> dict:
    """Sync KNUIS and LMS with credentials kept only for this background task."""
    from sync.knuis_sync import run_portal_sync

    mark_portal_sync_started(student_id)
    result: dict = {"portal": None, "lms": None}
    try:
        result["portal"] = run_portal_sync(
            student_id,
            storage_state=storage_state,
            on_step=lambda stage: _set_sync_stage(student_id, stage),
        )
        try:
            result["lms"] = sync_lms_data(student_id, password)
        except Exception as error:
            _set_lms_error(student_id, error)
            result["lms"] = {
                "success": False,
                "message": str(error),
            }
        return result
    finally:
        password = ""
        _finish_sync(student_id)


def sync_portal_profile(student_id: str, storage_state: dict) -> dict:
    """Compatibility alias for callers that previously requested profile-only sync."""
    return sync_portal_data(student_id, storage_state)
