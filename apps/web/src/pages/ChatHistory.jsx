import React from "react";
import { Icon } from "../icons.jsx";
import { useApp } from "../store.jsx";

// 오른쪽 접이식 대화목록 패널. 최근 대화 목록 + 새 대화 + 삭제.
// open/onClose는 Chatbot이 소유(패널 토글은 챗봇 화면 로컬 상태).
export function ChatHistory({ open, onClose }) {
  const { conversations, currentId, newConversation, loadConversation, deleteConversation } = useApp();

  return (
    <>
      {open && <div className="chat-hist-scrim" onClick={onClose} />}
      <aside className={"chat-hist" + (open ? " open" : "")}>
        <div className="chat-hist-head">
          <span>대화 목록</span>
          <button className="chat-hist-x" onClick={onClose} aria-label="패널 닫기">
            <Icon name="chevron" size={18} style={{ transform: "rotate(-90deg)" }} />
          </button>
        </div>
        <button className="chat-hist-new" onClick={() => { newConversation(); onClose(); }}>
          <Icon name="plus" size={16} /> 새 대화
        </button>
        <div className="chat-hist-list">
          {conversations.length === 0 && <div className="chat-hist-empty">저장된 대화가 없어요.</div>}
          {conversations.map((c) => (
            <div
              key={c.id}
              className={"chat-hist-item" + (c.id === currentId ? " on" : "")}
              onClick={() => { loadConversation(c.id); onClose(); }}
            >
              <span className="chat-hist-title">{c.title}</span>
              <button
                className="chat-hist-del"
                onClick={(e) => { e.stopPropagation(); deleteConversation(c.id); }}
                aria-label="대화 삭제"
              >
                <Icon name="trash" size={14} />
              </button>
            </div>
          ))}
        </div>
      </aside>
    </>
  );
}
