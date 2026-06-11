import React, { useState, useEffect } from "react";
import { Icon } from "../icons.jsx";
import { getNotices, NOTICE_CATEGORIES } from "../api.js";

function NoticeCard({ n }) {
  return (
    <div className={"notice-card" + (n.urgent ? " urgent" : "")}>
      <div className="nc-head">
        <div className="nc-source">
          {n.urgent && <span className="nc-urgent">URGENT</span>}
          <span className="nc-src-name">{n.source}</span>
          {n.dept && <><span className="nc-dot">•</span><span className="nc-dept">{n.dept}</span></>}
        </div>
        <div className="nc-dates">
          {n.deadlineLabel && (
            <div className={"nc-deadline" + (n.deadlineWarm ? " warm" : "")}>
              <Icon name="clock" size={13} /> {n.deadlineLabel}
            </div>
          )}
          <div className="nc-reg">{n.reg}</div>
        </div>
      </div>

      <div className="nc-title">{n.title}</div>
      <div className="nc-body">{n.body}</div>

      <div className="nc-foot">
        <div className="nc-tags">
          <span className="tag nc-target">{n.target}</span>
          {n.tags.map((t) => <span key={t} className="tag">{t}</span>)}
        </div>
        {n.attachments.length > 0 && (
          <div className="nc-files">
            {n.attachments.map((a) => (
              <span key={a} className="nc-file"><Icon name="file" size={13} /> {a}</span>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}

export function NoticesPage() {
  const [notices, setNotices] = useState([]);
  const [scope, setScope] = useState("My Dept");
  const [cat, setCat] = useState("All");
  const [q, setQ] = useState("");
  const [err, setErr] = useState("");
  useEffect(() => {
    getNotices().then(setNotices).catch((e) => setErr(e.message));
  }, []);

  const filtered = notices.filter((n) => {
    if (cat !== "All" && n.category !== cat) return false;
    if (q && !(n.title + n.body).toLowerCase().includes(q.toLowerCase())) return false;
    return true;
  });

  return (
    <div className="main-inner wide">
      <h1 className="page-title">University Notices</h1>
      <p className="page-sub">최신 학사·일반 공지를 확인하세요.</p>

      <div className="search-bar">
        <Icon name="search" size={18} />
        <input
          value={q}
          onChange={(e) => setQ(e.target.value)}
          placeholder="제목·내용으로 검색..."
        />
      </div>

      <div className="notices-filters">
        <div className="scope-toggle">
          {["My Dept", "All Notices"].map((s) => (
            <button key={s} className={"scope-btn" + (scope === s ? " on" : "")} onClick={() => setScope(s)}>{s}</button>
          ))}
        </div>
        <div className="cat-pills">
          {NOTICE_CATEGORIES.map((c) => (
            <button key={c} className={"cat-pill" + (cat === c ? " on" : "")} onClick={() => setCat(c)}>{c}</button>
          ))}
        </div>
      </div>

      <div className="notices-list">
        {filtered.map((n, i) => <NoticeCard key={i} n={n} />)}
        {filtered.length === 0 && <div className="caption" style={{ textAlign: "center", padding: 40 }}>{err || "표시할 공지사항이 없어요."}</div>}
      </div>
    </div>
  );
}
