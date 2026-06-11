import React, { useEffect } from "react";
import { Icon, Crest } from "../icons.jsx";
import { MOCK } from "../api.js";
import { useApp } from "../store.jsx";
import { todayClasses, parseCell } from "../timetable.js";

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
      <div className="hero">
        <div className="hero-crest"><Crest size={120} /></div>
        <div className="hero-text">
          <h1 className="hero-greet">{profile?.name ? `${profile.name}님, 안녕하세요` : "안녕하세요"}</h1>
          <p className="hero-sub">
            {profile?.major ? `${profile.major}${profile.year ? ` · ${profile.year}학년` : ""}` : "공주대학교 학사 어시스턴트"}
          </p>
        </div>
      </div>

      <div className="row-between" style={{ marginTop: 30 }}>
        <h2 className="section-title">추천 공지</h2>
      </div>
      <div className="rec-grid">
        {MOCK.recommended.map((n, i) => <RecCard key={i} n={n} />)}
      </div>

      <div className="card panel" style={{ marginTop: 22 }}>
        <div className="panel-head"><span style={{ display: "flex", alignItems: "center", gap: 9 }}><Icon name="clock" size={18} /> 다가오는 마감</span></div>
        <div className="dl-scroll">
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
      </div>

      <div className="card panel" style={{ marginTop: 18 }}>
        <div className="panel-head">
          <span style={{ display: "flex", alignItems: "center", gap: 9 }}><Icon name="calendar" size={18} /> 오늘 시간표</span>
          {today.length > 0 && <span className="caption">{today.length}과목</span>}
        </div>
        {today.length === 0
          ? <div className="tt-empty">{timetable ? "오늘은 수업이 없어요." : "포털을 연결하면 시간표가 표시됩니다."}</div>
          : <div className="tt-scroll">
              {today.map((c, i) => {
                const { name, room } = parseCell(c.name);
                return (
                  <div className="tt-item" key={i}>
                    <div className="tt-period">
                      <div className="tt-no">{c.no}</div>
                      <div className="tt-time">{c.time}</div>
                    </div>
                    <div className="tt-body">
                      <div className="tt-name">{name}</div>
                      {room && <div className="tt-room">{room}</div>}
                    </div>
                  </div>
                );
              })}
            </div>}
      </div>
    </div>
  );
}
