import React, { useEffect } from "react";
import { Icon } from "../icons.jsx";
import { MOCK } from "../api.js";
import { useApp } from "../store.jsx";

function RecCard({ n }) {
  return (
    <div className={"rec-card" + (n.active ? " active" : "")}>
      <div className="rec-top">
        <span className={"badge-d " + (n.warm ? "warm" : "cool")}>{n.d}</span>
      </div>
      <div className="rec-title">{n.title}</div>
      <div className="rec-body">{n.body}</div>
      <div className="rec-tags">
        {n.tags.map((t) => <span key={t} className="tag">{t}</span>)}
      </div>
    </div>
  );
}

function DeadlineRow({ d }) {
  return (
    <div className="dl-row">
      <span className={"dl-d " + (d.warm ? "warm" : "cool")}>{d.d}</span>
      <div className="dl-main">
        <div className="dl-title">{d.title}</div>
        <div className="dl-sub">{d.sub}</div>
      </div>
      <span className="tag dl-cat">{d.cat}</span>
    </div>
  );
}

function TtRow({ t }) {
  return (
    <div className={"tt-row" + (t.now ? " now" : "")}>
      <div className="tt-time">
        <div className="tt-start">{t.start || ""}</div>
        <div className="tt-end">{t.end || ""}</div>
      </div>
      <div className="tt-body">
        <div className="tt-title">{t.title || t.subject || ""}</div>
        <div className="tt-meta">
          {t.room && <span><Icon name="landmark" size={13} /> {t.room}</span>}
          {t.prof && <span><Icon name="user" size={13} /> {t.prof}</span>}
        </div>
      </div>
    </div>
  );
}

export function HomePage() {
  const { profile, timetable, loadTimetable } = useApp();
  useEffect(() => { loadTimetable(); }, [loadTimetable]);
  const tt = Array.isArray(timetable) ? timetable : [];

  return (
    <div className="main-inner wide">
      <h1 className="page-title" style={{ fontSize: 36 }}>{profile?.name ? `${profile.name}님, 안녕하세요!` : "안녕하세요!"}</h1>
      <p className="page-sub" style={{ fontSize: 16 }}>오늘도 좋은 하루 되세요.</p>

      <div className="row-between" style={{ marginTop: 32 }}>
        <h2 className="section-title">추천 공지</h2>
      </div>

      <div className="rec-grid">
        {MOCK.recommended.map((n, i) => <RecCard key={i} n={n} />)}
      </div>

      <div className="home-2col">
        <div className="card panel">
          <div className="panel-head"><span style={{ display: "flex", alignItems: "center", gap: 9 }}><Icon name="clock" size={18} /><span>다가오는 마감</span></span></div>
          <div className="dl-list">
            {MOCK.deadlines.map((d, i) => <DeadlineRow key={i} d={d} />)}
          </div>
        </div>

        <div className="card panel">
          <div className="panel-head">
            <span style={{ display: "flex", alignItems: "center", gap: 9 }}><Icon name="calendar" size={18} /><span>시간표</span></span>
          </div>
          <div className="tt-list">
            {tt.length === 0
              ? <div className="caption" style={{ padding: 28, textAlign: "center" }}>포털을 연결하면 시간표가 표시됩니다.</div>
              : tt.map((t, i) => <TtRow key={i} t={t} />)}
          </div>
        </div>
      </div>
    </div>
  );
}
