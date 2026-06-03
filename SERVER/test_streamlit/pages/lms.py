"""서버 테스트용 LMS 페이지. 외부 LMS 실행 + 학생별 LMS 할 일 관리."""

from datetime import date
from pathlib import Path
import subprocess
import sys

import streamlit as st
import streamlit.components.v1 as components

from db import (
    delete_lms_task,
    get_lms_courses,
    get_lms_tasks,
    set_favorite_courses,
    set_lms_task_done,
)
from test_streamlit.ui import get_current_user

LMS_URL = "https://knulms.kongju.ac.kr"
LMS_STATE_PATH = Path(".secrets/lms_storage_state.json")

TASK_TYPES = {
    "lecture": {"label": "남은 수강", "icon": "play_circle", "color": "#2563eb"},
    "assignment": {"label": "남은 과제", "icon": "assignment", "color": "#dc2626"},
    "notice": {"label": "LMS 알림", "icon": "campaign", "color": "#7c3aed"},
}


def _d_label(due_date, today: date) -> str:
    if not due_date:
        return "기한 없음"
    delta = (due_date - today).days
    if delta == 0:
        return "D-DAY"
    if delta > 0:
        return f"D-{delta}"
    return f"D+{-delta}"


def _task_meta(task: dict, today: date) -> str:
    parts = []
    if task.get("course_name"):
        parts.append(task["course_name"])
    parts.append(_d_label(task.get("due_date"), today))
    if task.get("progress") is not None:
        parts.append(f"진도 {task['progress']}%")
    return " · ".join(parts)


def _render_metric_cards(tasks: list[dict]):
    counts = {
        key: len([t for t in tasks if t["task_type"] == key and not t["is_done"]])
        for key in TASK_TYPES
    }
    cols = st.columns(3)
    for col, (task_type, spec) in zip(cols, TASK_TYPES.items()):
        with col:
            st.metric(spec["label"], counts[task_type])


def _render_task_card(task: dict, today: date, student_id: str):
    spec = TASK_TYPES[task["task_type"]]
    overdue = task.get("due_date") and task["due_date"] < today and not task["is_done"]
    title = task["title"]
    if task["is_done"]:
        title = f"~~{title}~~"

    with st.container(border=True):
        left, right = st.columns([5, 1])
        with left:
            st.markdown(
                f":material/{spec['icon']}: "
                f"<span style='color:{spec['color']};font-weight:700'>{spec['label']}</span>",
                unsafe_allow_html=True,
            )
            if task.get("url"):
                st.markdown(f"**[{title}]({task['url']})**")
            else:
                st.markdown(f"**{title}**")
            meta = _task_meta(task, today)
            if overdue:
                meta += " · 기한 지남"
            st.caption(meta)
        with right:
            done = st.checkbox(
                "완료",
                value=task["is_done"],
                key=f"lms_done_{task['id']}",
                label_visibility="collapsed",
            )
            if done != task["is_done"]:
                set_lms_task_done(task["id"], student_id, done)
                st.rerun()

            if st.button(
                "삭제",
                key=f"lms_delete_{task['id']}",
                use_container_width=True,
            ):
                delete_lms_task(task["id"], student_id)
                st.rerun()


def _sync_lms_tasks(student_id: str):
    return subprocess.run(
        [
            sys.executable,
            "sync/lms_sync.py",
            "--student-id",
            student_id,
        ],
        cwd=Path.cwd(),
        capture_output=True,
        text=True,
        timeout=90,
        check=False,
    )


user = get_current_user()
student_id = user["student_id"]
favorite_courses = set(user.get("favorite_courses") or [])
today = date.today()

col_title, col_btn = st.columns([5, 2])
with col_title:
    st.title("LMS")
    st.caption("공주대학교 LMS를 열고, 수강·과제·알림을 한곳에서 확인해요.")
with col_btn:
    st.write("")  # Vertical spacing to align with title
    st.write("")
    if st.button("🔄 LMS 동기화", use_container_width=True):
        with st.spinner("LMS 동기화 중..."):
            result = _sync_lms_tasks(student_id)
            if result.returncode == 0:
                st.success("동기화 완료!")
                st.rerun()
            else:
                st.error("동기화 실패")

if LMS_STATE_PATH.exists() and not st.session_state.get("lms_synced_this_session"):
    with st.spinner("LMS 세션을 확인하고 할 일을 자동 동기화하는 중이에요."):
        result = _sync_lms_tasks(student_id)
    st.session_state.lms_synced_this_session = True
    if result.returncode == 0:
        st.toast(result.stdout.strip() or "LMS 동기화 완료")
    else:
        st.warning(result.stderr.strip() or result.stdout.strip() or "LMS 자동 동기화에 실패했어요. 다시 로그인해 주세요.")

tasks = get_lms_tasks(student_id, include_done=True)
_render_metric_cards(tasks)

st.write("")

show_done = st.toggle("완료된 작업 표시", value=False)


def _visible(ts: list[dict]) -> list[dict]:
    return [t for t in ts if show_done or not t["is_done"]]


def _render_favorite_section(task_type: str, empty_msg: str):
    """즐겨찾기 과목별 closed expander 안에 해당 task_type 카드 표시."""
    if not favorite_courses:
        st.info("즐겨찾기한 과목이 없어요. '과목' 탭에서 별표를 눌러 추가하세요.")
        return
    type_tasks = _visible([t for t in tasks if t["task_type"] == task_type])
    for cname in sorted(favorite_courses):
        course_tasks = [t for t in type_tasks if t.get("course_name") == cname]
        
        # notice 타입이면 최신 알림순(due_date 내림차순)으로 정렬
        if task_type == "notice":
            course_tasks = sorted(
                course_tasks,
                key=lambda x: x.get("due_date") or date.min,
                reverse=True
            )

        with st.expander(cname, expanded=False):
            if not course_tasks:
                st.caption(empty_msg)
            else:
                for task in course_tasks:
                    _render_task_card(task, today, student_id)


tab_courses, tab_notices, tab_lectures, tab_assignments = st.tabs(
    ["과목", "알림", "남은 수강", "남은 과제"]
)

with tab_courses:
    courses = get_lms_courses(student_id)
    if not courses:
        st.info("등록된 과목이 없어요. 위 '🔄 할 일 동기화' 를 실행하세요.")
    else:
        for course in courses:
            cname = course["course_name"]
            is_fav = cname in favorite_courses
            with st.container(border=True):
                left, right = st.columns([6, 1])
                with left:
                    st.markdown(f"**{cname}**")
                with right:
                    icon = "⭐" if is_fav else "☆"
                    if st.button(
                        icon,
                        key=f"fav_btn_{course['course_id']}",
                        help="즐겨찾기 토글",
                        use_container_width=True,
                    ):
                        new_favs = (
                            favorite_courses - {cname}
                            if is_fav
                            else favorite_courses | {cname}
                        )
                        set_favorite_courses(student_id, sorted(new_favs))
                        st.rerun()

with tab_notices:
    _render_favorite_section("notice", "표시할 알림이 없어요.")

with tab_lectures:
    _render_favorite_section("lecture", "표시할 강의가 없어요.")

with tab_assignments:
    _render_favorite_section("assignment", "표시할 과제가 없어요.")
