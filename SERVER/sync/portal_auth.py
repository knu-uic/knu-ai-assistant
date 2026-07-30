"""Fast KNU portal credential verification for Codmes plugin login."""

from __future__ import annotations

import re
import time
import tempfile
from pathlib import Path
from threading import Lock

from sync.common import DEFAULT_PORTAL_URL

_syncing_student_ids: set[str] = set()
_sync_stage_by_student: dict[str, str] = {}
_portal_error_by_student: dict[str, str] = {}
_lms_error_by_student: dict[str, str] = {}
_syncing_lock = Lock()


def mark_portal_sync_started(student_id: str) -> None:
    with _syncing_lock:
        _syncing_student_ids.add(student_id)
        _sync_stage_by_student[student_id] = "학교 데이터 동기화 준비 중"
        _portal_error_by_student.pop(student_id, None)
        _lms_error_by_student.pop(student_id, None)


def is_portal_syncing(student_id: str) -> bool:
    with _syncing_lock:
        return student_id in _syncing_student_ids


def portal_sync_status(student_id: str) -> dict:
    with _syncing_lock:
        return {
            "syncing": student_id in _syncing_student_ids,
            "stage": _sync_stage_by_student.get(student_id),
            "portal_error": _portal_error_by_student.get(student_id),
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


def _set_portal_error(student_id: str, error: Exception | str) -> None:
    message = str(error).strip() or "알 수 없는 오류"
    with _syncing_lock:
        _portal_error_by_student[student_id] = message[:500]


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


def parse_portal_identity(
    student_id: str,
    name_text: str,
    department_text: str,
) -> dict:
    """Parse the common portal user widget shown immediately after SSO login."""
    name_match = re.search(r"^\s*(.+?)\s*\((\d+)\)", name_text or "")
    if not name_match:
        raise RuntimeError("포털 사용자 이름과 학번을 해석하지 못했습니다.")
    parsed_name, parsed_student_id = name_match.groups()
    if parsed_student_id != student_id:
        raise RuntimeError("로그인 계정과 포털 사용자 정보의 학번이 일치하지 않습니다.")

    department_parts = [
        part.strip() for part in (department_text or "").split("/") if part.strip()
    ]
    if not department_parts:
        raise RuntimeError("포털 사용자 정보에서 학과를 확인하지 못했습니다.")
    return {
        "name": parsed_name.strip(),
        "major": department_parts[0],
        "academic_status": department_parts[1] if len(department_parts) > 1 else None,
    }


def extract_portal_identity(page, student_id: str) -> dict | None:
    """Read identity fields from the portal home iframe without entering KNUIS."""
    name_selector = '[id="frmInsa_s.txtNm"]'
    department_selector = '[id="frmInsa_s.txtdept"]'
    for frame in page.frames:
        try:
            name = frame.locator(name_selector)
            department = frame.locator(department_selector)
            if name.count() != 1 or department.count() != 1:
                continue
            name_text = name.get_attribute("value") or name.text_content() or ""
            department_text = (
                department.get_attribute("value") or department.text_content() or ""
            )
            return parse_portal_identity(student_id, name_text, department_text)
        except Exception:
            continue
    return None


def save_portal_identity(student_id: str, profile: dict | None) -> None:
    """Persist the identity available at login before slower KNUIS/LMS sync."""
    if not profile:
        return
    from db.users import upsert_user

    upsert_user(
        student_id=student_id,
        name=profile["name"],
        major=profile["major"],
        year=None,
    )


def authenticate_portal(student_id: str, password: str) -> dict | None:
    """Verify university SSO and return session state plus portal identity."""
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
                    return {
                        "storage_state": context.storage_state(),
                        "profile": extract_portal_identity(page, student_id.strip()),
                    }
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
        result = run_portal_sync(
            student_id,
            storage_state=storage_state,
            on_step=lambda stage: _set_sync_stage(student_id, stage),
        )
        if not result.get("success"):
            _set_portal_error(
                student_id,
                result.get("message") or "포털 데이터 동기화에 실패했습니다.",
            )
        return result
    except Exception as error:
        _set_portal_error(student_id, error)
        raise
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
    portal_profile: dict | None = None,
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
            initial_profile=portal_profile,
        )
        if not result["portal"].get("success"):
            _set_portal_error(
                student_id,
                result["portal"].get("message") or "포털 데이터 동기화에 실패했습니다.",
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
    except Exception as error:
        _set_portal_error(student_id, error)
        raise
    finally:
        password = ""
        _finish_sync(student_id)


def sync_portal_profile(student_id: str, storage_state: dict) -> dict:
    """Compatibility alias for callers that previously requested profile-only sync."""
    return sync_portal_data(student_id, storage_state)
