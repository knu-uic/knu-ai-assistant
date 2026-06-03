"""LMS·포털 연동 오케스트레이션 + 신원/연동상태 중앙화.

페이지(설정 등)와 진입점이 공유하는 연동 실행·상태 판별을 한곳에 모은다.
2-2(멀티유저 토큰 쿠키)에서는 get_student_id() 한 함수만 쿠키 조회로 교체하면
페이지 코드 변경 없이 확장된다.
"""

import json
import subprocess
import sys
from pathlib import Path

import streamlit as st

from db import get_user
from ui import CURRENT_STUDENT_ID_KEY

LMS_STATE_PATH = Path(".secrets/lms_storage_state.json")
LMS_CURRENT_USER_PATH = Path(".secrets/lms_current_user.json")
LMS_TOKEN_PATH = LMS_STATE_PATH.parent / "lms_canvas_token.txt"


# ── 연동 실행 (subprocess) ─────────────────────────────────────

def login_lms(username: str, password: str):
    """LMS(LearningX) 로그인. 성공 시 .secrets/lms_storage_state.json에 세션 쿠키 저장."""
    return subprocess.run(
        [sys.executable, "lms_login.py", "--username", username, "--password-stdin", "--timeout", "60"],
        cwd=Path.cwd(),
        input=password + "\n",
        capture_output=True,
        text=True,
        timeout=90,
        check=False,
    )


def sync_portal(username: str, password: str):
    """KNUIS 포털 크롤(학적·취득학점·성적·시간표) → DB 저장. 느려서 타임아웃 240."""
    return subprocess.run(
        [sys.executable, "knuis_sync.py", "--username", username, "--password-stdin"],
        cwd=Path.cwd(),
        input=password + "\n",
        capture_output=True,
        text=True,
        timeout=240,
        check=False,
    )


# ── 신원 / 연동 상태 ───────────────────────────────────────────

def get_student_id() -> str | None:
    """현재 신원(학번). 세션 → LMS current-user 파일 순. 없으면 None(익명).

    (2-2 멀티유저: 이 함수만 세션 토큰 쿠키 조회로 교체.)
    """
    sid = st.session_state.get(CURRENT_STUDENT_ID_KEY)
    if sid:
        return sid
    if LMS_CURRENT_USER_PATH.exists():
        try:
            data = json.loads(LMS_CURRENT_USER_PATH.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            data = {}
        sid = data.get("student_id")
        if sid:
            st.session_state[CURRENT_STUDENT_ID_KEY] = sid
            return sid
    return None


def lms_linked() -> bool:
    return LMS_STATE_PATH.exists()


def portal_linked() -> bool:
    sid = get_student_id()
    if not sid:
        return False
    user = get_user(sid)
    return bool(
        user
        and (
            user.get("cumulative_grades")
            or user.get("grade_distribution")
            or user.get("timetable")
        )
    )


def clear_links():
    """연동 해제: LMS 세션 파일/토큰/현재사용자 파일 삭제 + 세션 신원 제거."""
    for path in (LMS_STATE_PATH, LMS_CURRENT_USER_PATH, LMS_TOKEN_PATH):
        if path.exists():
            try:
                path.unlink()
            except Exception:
                pass
    st.session_state.pop(CURRENT_STUDENT_ID_KEY, None)
