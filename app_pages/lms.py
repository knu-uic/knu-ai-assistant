"""LMS 페이지. 외부 LMS 실행 + 학생별 LMS 할 일 관리."""

from datetime import date
from pathlib import Path
import subprocess
import sys

import streamlit as st
import streamlit.components.v1 as components

from db import add_lms_task, delete_lms_task, get_lms_tasks, set_lms_task_done
from ui import get_current_user

LMS_URL = "https://knulms.kongju.ac.kr"
LMS_STATE_PATH = Path(".secrets/lms_storage_state.json")
LMS_LOGIN_LOG_PATH = Path(".secrets/lms_login.log")

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


def _start_lms_login():
    LMS_LOGIN_LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    log_file = LMS_LOGIN_LOG_PATH.open("a", encoding="utf-8")
    process = subprocess.Popen(
        [
            sys.executable,
            "lms_login.py",
            "--auto",
            "--timeout",
            "300",
        ],
        cwd=Path.cwd(),
        stdout=log_file,
        stderr=subprocess.STDOUT,
        start_new_session=True,
    )
    log_file.close()
    st.session_state.lms_login_pid = process.pid


def _sync_lms_tasks(student_id: str):
    return subprocess.run(
        [
            sys.executable,
            "lms_sync.py",
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
today = date.today()

st.title("LMS")
st.caption("공주대학교 LMS를 열고, 수강·과제·알림을 한곳에서 확인해요.")

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

tab_dashboard, tab_lms = st.tabs(["내 LMS 할 일", "LMS 실행"])

with tab_dashboard:
    c1, c_sync, c2 = st.columns([3, 1, 1])
    with c1:
        st.subheader("남은 항목")
    with c_sync:
        if st.button("자동 동기화", type="primary", use_container_width=True):
            if not LMS_STATE_PATH.exists():
                _start_lms_login()
                st.info("LMS 로그인 창을 열었어요. 로그인하면 세션이 자동 저장됩니다. 완료 후 이 페이지에서 자동 동기화를 다시 눌러 주세요.")
            else:
                with st.spinner("Canvas API로 LMS 할 일을 동기화하는 중이에요."):
                    result = _sync_lms_tasks(student_id)
                if result.returncode == 0:
                    st.session_state.lms_synced_this_session = True
                    st.success(result.stdout.strip() or "LMS 동기화가 완료됐어요.")
                    st.rerun()
                else:
                    st.error(result.stderr.strip() or result.stdout.strip() or "LMS 동기화에 실패했어요.")
    with c2:
        show_done = st.toggle("완료 표시", value=False)

    if not LMS_STATE_PATH.exists():
        login_cols = st.columns([1, 4])
        with login_cols[0]:
            if st.button("LMS 로그인", use_container_width=True):
                _start_lms_login()
                st.info("로그인 창을 열었어요. 열린 브라우저에서 LMS 로그인을 완료해 주세요.")
        with login_cols[1]:
            st.caption("최초 1회만 앱에서 LMS 로그인 창을 열면 됩니다. 로그인 성공이 확인되면 세션이 자동 저장되고 이후 앱 진입 시 할 일이 동기화돼요.")
    else:
        st.caption("LMS 세션이 저장되어 있어요. 이 페이지에 들어오면 세션을 사용해 할 일을 자동 동기화합니다.")

    visible_tasks = [t for t in tasks if show_done or not t["is_done"]]
    if not visible_tasks:
        st.info("등록된 LMS 할 일이 없어요.")
    else:
        for task in visible_tasks:
            _render_task_card(task, today, student_id)

    st.write("")
    with st.expander("LMS 할 일 추가", expanded=not tasks):
        with st.form("add_lms_task", clear_on_submit=True):
            task_type_label = st.segmented_control(
                "종류",
                [spec["label"] for spec in TASK_TYPES.values()],
                default=TASK_TYPES["lecture"]["label"],
            )
            selected_type = next(
                key for key, spec in TASK_TYPES.items()
                if spec["label"] == task_type_label
            )

            title = st.text_input("제목", placeholder="예: 3주차 온라인 강의")
            c_course, c_due, c_progress = st.columns([2, 1, 1])
            course_name = c_course.text_input("과목", placeholder="예: 인공지능개론")
            due_date = c_due.date_input("기한", value=None)
            progress = None
            if selected_type == "lecture":
                progress = c_progress.number_input(
                    "진도율",
                    min_value=0,
                    max_value=100,
                    value=0,
                    step=5,
                )
            else:
                c_progress.write("")

            url = st.text_input("링크", value=LMS_URL)
            submitted = st.form_submit_button("추가", type="primary")
            if submitted:
                if not title.strip():
                    st.warning("제목을 입력해 주세요.")
                else:
                    add_lms_task(
                        student_id=student_id,
                        task_type=selected_type,
                        title=title.strip(),
                        course_name=course_name.strip() or None,
                        due_date=due_date,
                        progress=int(progress) if progress is not None else None,
                        url=url.strip() or None,
                    )
                    st.success("LMS 할 일을 추가했어요.")
                    st.rerun()

with tab_lms:
    top = st.columns([1, 1, 4])
    with top[0]:
        st.link_button("새 탭에서 열기", LMS_URL, use_container_width=True)
    with top[1]:
        if st.button("다시 불러오기", use_container_width=True):
            st.rerun()

    st.caption("학교 SSO 로그인 화면이 보이면 그대로 로그인하면 됩니다. 브라우저 보안 정책으로 화면이 비어 보일 때는 새 탭에서 열어 주세요.")
    components.iframe(LMS_URL, height=760, scrolling=True)
