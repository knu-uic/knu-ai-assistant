import React, { useEffect } from "react";
import { Icon, Crest } from "../icons.jsx";
import { useApp } from "../store.jsx";
import { todayClasses, parseCell } from "../timetable.js";

function RecCard({ n }) {
  const card = (
    <>
      {n.d && <span className={"badge-d " + (n.warm ? "warm" : "cool")}>{n.d}</span>}
      <div className="rec-title">{n.title}</div>
      <div className="rec-body">{n.body}</div>
      <div className="rec-tags">{n.tags.map((t) => <span key={t} className="tag">{t}</span>)}</div>
    </>
  );
  return n.url
    ? <a className="rec-card" href={n.url} target="_blank" rel="noreferrer">{card}</a>
    : <div className="rec-card">{card}</div>;
}

export function HomePage() {
  const { profile, timetable, loadTimetable, home, loadHome } = useApp();
  useEffect(() => { loadTimetable(); loadHome(); }, [loadTimetable, loadHome]);
  const today = todayClasses(timetable);
  const recommended = home?.recommended || [];
  const deadlines = home?.deadlines || [];

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
      {recommended.length === 0
        ? <div className="tt-empty">{home ? "아직 추천할 공지가 충분히 모이지 않았어요. 설정에서 관심사를 등록해보세요." : "불러오는 중..."}</div>
        : <div className="rec-grid">
            {recommended.map((n, i) => <RecCard key={n.url || i} n={n} />)}
          </div>}

      <div className="card panel" style={{ marginTop: 22 }}>
        <div className="panel-head"><span style={{ display: "flex", alignItems: "center", gap: 9 }}><Icon name="clock" size={18} /> 다가오는 마감</span></div>
        {deadlines.length === 0
          ? <div className="tt-empty">{home ? "30일 안에 마감되는 공지가 없어요." : "불러오는 중..."}</div>
          : <div className="dl-scroll">
              {deadlines.map((d, i) => (
                <a className="dl-row" key={d.url || i} href={d.url} target="_blank" rel="noreferrer">
                  <span className={"dl-d " + (d.warm ? "warm" : "cool")}>{d.d}</span>
                  <div className="dl-main">
                    <div className="dl-title">{d.title}</div>
                    <div className="dl-sub">{d.sub}</div>
                  </div>
                  {d.cat && <span className="tag">{d.cat}</span>}
                </a>
              ))}
            </div>}
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
