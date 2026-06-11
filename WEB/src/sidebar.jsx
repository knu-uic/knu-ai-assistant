import React from "react";
import { Icon, Crest } from "./icons.jsx";

const NAV = [
  { id: "home", icon: "home", label: "Home" },
  { id: "notices", icon: "bell", label: "Notices" },
  { id: "lms", icon: "book", label: "LMS" },
  { id: "portal", icon: "landmark", label: "Portal" },
  { id: "chatbot", icon: "bot", label: "AI Chatbot" },
  { id: "settings", icon: "settings", label: "Settings" },
];

export function Sidebar({ page, onNav }) {
  return (
    <aside className="sidebar">
      <div className="brand">
        <Crest size={34} />
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

      <div className="sidebar-foot">
        <button
          className="foot-user"
          onClick={() => onNav("settings")}
          style={{ border: "none", background: "none", width: "100%" }}
        >
          <Icon name="user" />
          <span>Student Profile</span>
        </button>
      </div>
    </aside>
  );
}
