import React from "react";
import { Icon } from "./icons.jsx";

const NAV = [
  { id: "home", icon: "home", label: "홈" },
  { id: "notices", icon: "bell", label: "공지" },
  { id: "lms", icon: "book", label: "LMS" },
  { id: "portal", icon: "landmark", label: "포털" },
  { id: "chatbot", icon: "bot", label: "AI 챗봇" },
  { id: "settings", icon: "user", label: "프로필" },
];

export function Sidebar({ page, onNav }) {
  return (
    <aside className="sidebar">
      <div className="brand">
        <div>
          <div className="brand-name">KNU PICK</div>
          <div className="brand-sub">Academic Intelligence</div>
        </div>
      </div>
      <nav className="nav">
        {NAV.map((n) => (
          <button
            key={n.id}
            className={"nav-item" + (page === n.id ? " active" : "")}
            onClick={() => onNav(n.id)}
          >
            <Icon name={n.icon} />
            <span>{n.label}</span>
          </button>
        ))}
      </nav>
    </aside>
  );
}
