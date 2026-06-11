import React, { useState, useEffect } from "react";
import { Icon } from "../icons.jsx";
import { useApp } from "../store.jsx";

const TASK_TYPES = {
  lecture: { label: "남은 수강", icon: "play", color: "#2563eb" },
  assignment: { label: "남은 과제", icon: "fileText", color: "#d23b4a" },
  notice: { label: "LMS 알림", icon: "bell", color: "#7c3aed" },
};

function dLabel(iso) {
  if (!iso) return "기한 없음";
  const today = new Date(); today.setHours(0, 0, 0, 0);
  const due = new Date(iso); due.setHours(0, 0, 0, 0);
  const delta = Math.round((due - today) / 86400000);
  if (delta === 0) return "D-DAY";
  return delta > 0 ? `D-${delta}` : `D+${-delta}`;
}

function taskMeta(t) {
  const parts = [];
  if (t.course && t.course !== "기타") parts.push(t.course);
  parts.push(dLabel(t.due_date));
  if (t.progress != null) parts.push(`진도 ${t.progress}%`);
  return parts.join(" · ");
}

function TaskCard({ t, onToggle, onDelete }) {
  const spec = TASK_TYPES[t.type] || TASK_TYPES.notice;
  return (
    <div className="task-card">
      <button className={"task-check" + (t.done ? " on" : "")} onClick={() => onToggle(t.id, !t.done)}>
        {t.done && <Icon name="check" size={13} />}
      </button>
      <div className="task-main">
        <div className="task-type" style={{ color: spec.color }}>
          <Icon name={spec.icon} size={12} style={{ verticalAlign: "-1px", marginRight: 4 }} />{spec.label}
        </div>
        <div className={"task-title" + (t.done ? " done" : "")}>
          {t.url ? <a href={t.url} target="_blank" rel="noreferrer">{t.title}</a> : t.title}
        </div>
        <div className="task-meta">{taskMeta(t)}</div>
      </div>
      <button className="task-del" onClick={() => onDelete(t.id)}>삭제</button>
    </div>
  );
}

function Expander({ name, count, children }) {
  const [open, setOpen] = useState(false);
  return (
    <div className={"expander" + (open ? " open" : "")}>
      <button className="exp-head" onClick={() => setOpen(!open)}>
        <span className="exp-name">{name}</span>
        {count > 0 && (
          <span className="exp-dots" title={`${count}건`}>
            {Array.from({ length: Math.min(count, 6) }).map((_, i) => <span key={i} className="dot" />)}
            {count > 6 && <span className="dot-more">+{count - 6}</span>}
          </span>
        )}
        <Icon name="chevron" size={16} className="exp-chev" />
      </button>
      {open && <div className="exp-body">{children}</div>}
    </div>
  );
}

export function LmsPage() {
  const {
    profile, lmsTasks, lmsCourses, loadLms, syncLms,
    saveFavorites, toggleTaskDone, removeTask,
  } = useApp();
  const [tab, setTab] = useState("courses");
  const [syncing, setSyncing] = useState(false);
  const [msg, setMsg] = useState("");

  useEffect(() => { loadLms(); }, [loadLms]);

  const tasks = lmsTasks || [];
  const courses = lmsCourses || [];
  const favorites = profile?.favorite_courses || [];

  const counts = {
    lecture: tasks.filter((t) => t.type === "lecture" && !t.done).length,
    assignment: tasks.filter((t) => t.type === "assignment" && !t.done).length,
    notice: tasks.filter((t) => t.type === "notice" && !t.done).length,
  };

  async function doSync() {
    if (!profile?.student_id) { setMsg("설정에서 포털을 먼저 연결해주세요."); return; }
    setSyncing(true); setMsg("");
    try { await syncLms(profile.student_id, undefined, setMsg); setMsg(""); }
    catch (e) { setMsg(e.needsReconnect ? "포털 재연결이 필요해요(설정)." : e.message); }
    finally { setSyncing(false); }
  }

  function toggleFav(cname) {
    const next = favorites.includes(cname)
      ? favorites.filter((c) => c !== cname)
      : [...favorites, cname];
    saveFavorites(next);
  }

  function favSection(type, empty) {
    if (favorites.length === 0)
      return <div className="empty-msg">즐겨찾기한 과목이 없어요. '과목' 탭에서 별표를 눌러 추가하세요.</div>;
    return [...favorites].sort().map((cname) => {
      let items = tasks.filter((t) => t.type === type && t.course === cname && !t.done);
      if (type === "notice") items = items.sort((a, b) => (b.due_date || "").localeCompare(a.due_date || ""));
      return (
        <Expander key={cname} name={cname} count={items.length}>
          {items.length === 0
            ? <div className="caption" style={{ padding: "8px 4px" }}>{empty}</div>
            : items.map((t) => <TaskCard key={t.id} t={t} onToggle={toggleTaskDone} onDelete={removeTask} />)}
        </Expander>
      );
    });
  }

  const TABS = [
    { id: "courses", label: "과목" },
    { id: "notice", label: "알림" },
    { id: "lecture", label: "남은 수강" },
    { id: "assignment", label: "남은 과제" },
  ];

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
            <div className="lm-label">{spec.label}</div>
            <div className="lm-count">{counts[k]}</div>
          </div>
        ))}
      </div>

      <div className="tabs">
        {TABS.map((t) => (
          <button key={t.id} className={"tab" + (tab === t.id ? " on" : "")} onClick={() => setTab(t.id)}>{t.label}</button>
        ))}
      </div>

      {tab === "courses" && (
        courses.length === 0
          ? <div className="empty-msg">{lmsCourses ? "등록된 과목이 없어요. 'LMS 동기화'를 실행하세요." : "불러오는 중..."}</div>
          : courses.map((c) => {
              const fav = favorites.includes(c.course_name);
              return (
                <div className="course-row" key={c.course_id}>
                  <span className="course-name">{c.course_name}</span>
                  <button className={"fav-btn" + (fav ? " on" : "")} onClick={() => toggleFav(c.course_name)} title="즐겨찾기">
                    <Icon name={fav ? "starFill" : "star"} size={20} />
                  </button>
                </div>
              );
            })
      )}
      {tab === "notice" && favSection("notice", "표시할 알림이 없어요.")}
      {tab === "lecture" && favSection("lecture", "표시할 강의가 없어요.")}
      {tab === "assignment" && favSection("assignment", "표시할 과제가 없어요.")}
    </div>
  );
}
