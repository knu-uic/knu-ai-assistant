import React, { useState, useEffect } from "react";
import { Icon } from "../icons.jsx";
import { NOTICE_CATEGORIES } from "../api.js";
import { useApp } from "../store.jsx";

function NoticeCard({ n }) {
  return (
    <a className="notice-card" href={n.url || "#"} target="_blank" rel="noreferrer">
      <div className="nc-head">
        <div className="nc-source">
          <span className="nc-src-name">{n.source}</span>
          {n.dept && <><span className="nc-dot">•</span><span className="nc-dept">{n.dept}</span></>}
        </div>
        <div style={{ textAlign: "right" }}>
          {n.deadlineLabel && <div className={"nc-deadline" + (n.deadlineWarm ? " warm" : "")}><Icon name="clock" size={13} /> {n.deadlineLabel}</div>}
          <div className="nc-reg">{n.reg}</div>
        </div>
      </div>
      <div className="nc-title">{n.title}</div>
      <div className="nc-body">{n.body}</div>
      <div className="nc-foot">
        <span className="tag">{n.target}</span>
        {n.tags.map((t) => <span key={t} className="tag">{t}</span>)}
      </div>
    </a>
  );
}

export function NoticesPage() {
  const { notices, loadNotices, profile } = useApp();
  const [cat, setCat] = useState("전체");
  const [q, setQ] = useState("");
  const [err, setErr] = useState("");
  useEffect(() => { loadNotices().catch((e) => setErr(e.message)); }, [loadNotices]);

  const list = notices || [];
  const filtered = list.filter((n) => {
    if (cat !== "전체" && n.category !== cat) return false;
    if (q && !(n.title + n.body).toLowerCase().includes(q.toLowerCase())) return false;
    return true;
  });

  return (
    <div className="main-inner wide">
      <h1 className="page-title">공지사항</h1>
      <p className="page-sub">최신 학사·일반 공지를 확인하세요.</p>

      {profile && !profile.portal_linked && (
        <div className="banner" style={{ marginBottom: 14 }}>
          포털을 연결하면 내 학과 공지도 함께 볼 수 있어요. 지금은 전체 공통 공지만 표시됩니다.
        </div>
      )}

      <div className="search-bar">
        <Icon name="search" size={18} />
        <input value={q} onChange={(e) => setQ(e.target.value)} placeholder="제목·내용으로 검색..." />
      </div>

      <div className="cat-pills">
        {NOTICE_CATEGORIES.map((c) => (
          <button key={c} className={"cat-pill" + (cat === c ? " on" : "")} onClick={() => setCat(c)}>{c}</button>
        ))}
      </div>

      <div className="notices-list">
        {filtered.map((n, i) => <NoticeCard key={i} n={n} />)}
        {filtered.length === 0 && <div className="empty-msg">{err || (notices ? "표시할 공지사항이 없어요." : "불러오는 중...")}</div>}
      </div>
    </div>
  );
}
