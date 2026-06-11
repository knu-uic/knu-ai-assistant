import React, { useEffect } from "react";
import { Icon } from "../icons.jsx";
import { MOCK } from "../api.js";
import { useApp } from "../store.jsx";
import { todayClasses } from "../timetable.js";

function RecCard({ n }) {
  return (
    <div className={"rec-card" + (n.active ? " active" : "")}>
      <span className={"badge-d " + (n.warm ? "warm" : "cool")}>{n.d}</span>
      <div className="rec-title">{n.title}</div>
      <div className="rec-body">{n.body}</div>
      <div className="rec-tags">{n.tags.map((t) => <span key={t} className="tag">{t}</span>)}</div>
    </div>
  );
}

export function HomePage() {
  const { profile, timetable, loadTimetable } = useApp();
  useEffect(() => { loadTimetable(); }, [loadTimetable]);
  const today = todayClasses(timetable);

  return (
    <div className="main-inner wide">
      <h1 className="greet">{profile?.name ? `${profile.name}님, 안녕하세요` : "안녕하세요"}</h1>
      <p className="page-sub" style={{ fontSize: 15.5 }}>오늘도 좋은 하루 되세요.</p>

      <div className="row-between" style={{ marginTop: 30 }}>
        <h2 className="section-title">추천 공지</h2>
      </div>
      <div className="rec-grid">
        {MOCK.recommended.map((n, i) => <RecCard key={i} n={n} />)}
      </div>

      <div className="home-2col">
        <div className="card panel">
          <div className="panel-head"><span style={{ display: "flex", alignItems: "center", gap: 9 }}><Icon name="clock" size={18} /> 다가오는 마감</span></div>
          {MOCK.deadlines.map((d, i) => (
            <div className="dl-row" key={i}>
              <span className={"dl-d " + (d.warm ? "warm" : "cool")}>{d.d}</span>
              <div className="dl-main">
                <div className="dl-title">{d.title}</div>
                <div className="dl-sub">{d.sub}</div>
              </div>
              <span className="tag">{d.cat}</span>
            </div>
          ))}
        </div>

        <div className="card panel">
          <div className="panel-head"><span style={{ display: "flex", alignItems: "center", gap: 9 }}><Icon name="calendar" size={18} /> 오늘 시간표</span></div>
          {today.length === 0
            ? <div className="tt-empty">{timetable ? "오늘은 수업이 없어요." : "포털을 연결하면 시간표가 표시됩니다."}</div>
            : today.map((c, i) => (
                <div className="tt-item" key={i}>
                  <span className="tt-period">{c.period}</span>
                  <span className="tt-name">{c.name}</span>
                </div>
              ))}
        </div>
      </div>
    </div>
  );
}
