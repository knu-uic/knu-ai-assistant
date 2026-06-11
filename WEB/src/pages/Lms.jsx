import React, { useState, useEffect } from "react";
import { Icon } from "../icons.jsx";
import { useApp } from "../store.jsx";

const TASK_TYPES = {
  lecture: { label: "남은 수강", icon: "play", color: "#15539c", bg: "#e8f1fb" },
  assignment: { label: "남은 과제", icon: "fileText", color: "#d23b4a", bg: "#fdecee" },
  notice: { label: "LMS 알림", icon: "bell", color: "#b88a2b", bg: "#f6efdd" },
};
const SECTION_ORDER = ["lecture", "assignment", "notice"];

function TaskRow({ t }) {
  const spec = TASK_TYPES[t.type] || TASK_TYPES.notice;
  return (
    <div className="lms-task">
      <div className="lt-main">
        <div className="lt-title">{t.title}</div>
        <div className="lt-meta">
          <span className="lt-d">{t.due}</span>
          {t.progress != null && (
            <span className="lt-prog">
              <span className="lt-bar"><span style={{ width: t.progress + "%", background: spec.color }}></span></span>
              진도 {t.progress}%
            </span>
          )}
        </div>
      </div>
    </div>
  );
}

function CourseAccordion({ course, tasks, open, onToggleOpen }) {
  const counts = {
    lecture: tasks.filter((t) => t.type === "lecture").length,
    assignment: tasks.filter((t) => t.type === "assignment").length,
    notice: tasks.filter((t) => t.type === "notice").length,
  };
  const total = tasks.length;
  return (
    <div className={"course-acc" + (open ? " open" : "")}>
      <button className="acc-head" onClick={onToggleOpen}>
        <span className="acc-name">{course.course_name}</span>
        <div className="acc-counts">
          {SECTION_ORDER.map((k) => counts[k] > 0 && (
            <span key={k} className="acc-count" style={{ color: TASK_TYPES[k].color, background: TASK_TYPES[k].bg }}>
              <Icon name={TASK_TYPES[k].icon} size={12} /> {counts[k]}
            </span>
          ))}
          {total === 0 && <span className="acc-empty">완료됨</span>}
        </div>
        <Icon name="chevron" size={16} className="acc-chev" />
      </button>
      {open && (
        <div className="acc-body">
          {total === 0
            ? <div className="acc-none">표시할 항목이 없어요.</div>
            : SECTION_ORDER.map((k) => {
                const items = tasks.filter((t) => t.type === k);
                if (items.length === 0) return null;
                return (
                  <div key={k} className="acc-section">
                    <div className="acc-sec-label" style={{ color: TASK_TYPES[k].color }}>
                      <Icon name={TASK_TYPES[k].icon} size={13} /> {TASK_TYPES[k].label} <span className="acc-sec-n">{items.length}</span>
                    </div>
                    <div className="acc-tasks">
                      {items.map((t) => <TaskRow key={t.id} t={t} />)}
                    </div>
                  </div>
                );
              })}
        </div>
      )}
    </div>
  );
}

export function LmsPage() {
  const { profile, lmsTasks, lmsCourses, loadLms, syncLms } = useApp();
  const [openId, setOpenId] = useState(null);
  const [syncing, setSyncing] = useState(false);
  const [msg, setMsg] = useState("");

  useEffect(() => { loadLms(); }, [loadLms]);

  const tasks = lmsTasks || [];
  const courses = lmsCourses || [];
  const counts = {
    lecture: tasks.filter((t) => t.type === "lecture" && !t.done).length,
    assignment: tasks.filter((t) => t.type === "assignment" && !t.done).length,
    notice: tasks.filter((t) => t.type === "notice" && !t.done).length,
  };

  async function doSync() {
    if (!profile?.student_id) { setMsg("설정에서 포털을 먼저 연결해주세요."); return; }
    setSyncing(true); setMsg("");
    try {
      await syncLms(profile.student_id, undefined, setMsg);
      setMsg("");
    } catch (e) {
      setMsg(e.needsReconnect ? "포털 재연결이 필요해요(설정 화면)." : e.message);
    } finally {
      setSyncing(false);
    }
  }

  return (
    <div className="main-inner wide">
      <div className="row-between" style={{ alignItems: "flex-start" }}>
        <div>
          <h1 className="page-title">LMS</h1>
          <p className="page-sub">과목별로 남은 수강·과제·알림을 한곳에서 확인해요.</p>
        </div>
        <button className="btn" onClick={doSync} disabled={syncing}>
          <Icon name="refresh" size={14} style={{ marginRight: 6, verticalAlign: "-2px" }} />
          {syncing ? (msg || "동기화 중...") : "LMS 동기화"}
        </button>
      </div>
      {msg && !syncing && <div className="caption" style={{ marginTop: 6 }}>{msg}</div>}

      <div className="lms-metrics">
        {Object.entries(TASK_TYPES).map(([k, spec]) => (
          <div key={k} className="lms-metric">
            <span className="lm-ico" style={{ color: spec.color, background: spec.bg }}><Icon name={spec.icon} size={16} /></span>
            <div>
              <div className="lm-label">{spec.label}</div>
              <div className="lm-count">{counts[k]}</div>
            </div>
          </div>
        ))}
      </div>

      <div className="acc-list">
        {courses.length === 0 && <div className="caption" style={{ textAlign: "center", padding: 40 }}>{lmsCourses ? "LMS를 동기화하면 과목이 표시됩니다." : "불러오는 중..."}</div>}
        {courses.map((c) => {
          const courseTasks = tasks.filter((t) => t.course === c.course_name && !t.done);
          return (
            <CourseAccordion
              key={c.course_id}
              course={c}
              tasks={courseTasks}
              open={openId === c.course_id}
              onToggleOpen={() => setOpenId(openId === c.course_id ? null : c.course_id)}
            />
          );
        })}
      </div>
    </div>
  );
}
