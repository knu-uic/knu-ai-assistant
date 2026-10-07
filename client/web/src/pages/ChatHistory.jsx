import React from "react";
import { Icon } from "../icons.jsx";
import { useApp } from "../store.jsx";

// 오른쪽 접이식 대화목록 패널. 최근 대화 목록 + 새 대화 + 삭제.
// open/onClose는 Chatbot이 소유(패널 토글은 챗봇 화면 로컬 상태).
export function ChatHistory({ open, onClose }) {
  const { conversations, currentId, newConversation, loadConversation, deleteConversation,
    historyBusy, chatGenerating, historyCursor, legacyAvailable, importConversations,
    refreshConversations, historyError, historyNotice } = useApp();
  const disabled=historyBusy || chatGenerating;

  return (
    <>
      {open && <div className="chat-hist-scrim" onClick={onClose} />}
      <aside className={"chat-hist" + (open ? " open" : "")} aria-hidden={!open} inert={open ? undefined : ''}>
        <div className="chat-hist-head">
          <span>대화 목록</span>
          <button className="chat-hist-x" onClick={onClose} aria-label="패널 닫기">
            <Icon name="chevron" size={18} style={{ transform: "rotate(-90deg)" }} />
          </button>
        </div>
        <button className="chat-hist-new" disabled={disabled} onClick={() => { if(newConversation()) onClose(); }}>
          <Icon name="plus" size={16} /> 새 대화
        </button>
        <button className="chat-hist-new" disabled={disabled} onClick={()=>refreshConversations()}>서버 기록 새로고침</button>
        {legacyAvailable && <button className="chat-hist-new" disabled={disabled} onClick={()=>{
          if(window.confirm('이 브라우저에 저장된 내 대화 기록을 KNU 서버로 가져올까요? 다른 기기에서도 볼 수 있게 됩니다. 브라우저 원본은 삭제하지 않습니다.')) importConversations();
        }}>기존 브라우저 기록 가져오기</button>}
        {(historyError || historyNotice) && <p role="status" className="chat-hist-empty">{historyError || historyNotice}</p>}
        {historyBusy && <p role="status" className="chat-hist-empty">서버 기록을 불러오고 있어요…</p>}
        <div className="chat-hist-list">
          {conversations.length === 0 && <div className="chat-hist-empty">저장된 대화가 없어요.</div>}
          {conversations.map((c) => (
            <div
              key={c.id}
              className={"chat-hist-item" + (c.id === currentId ? " on" : "")}
              role="button" tabIndex={disabled ? -1 : 0}
              aria-disabled={disabled}
              onKeyDown={async e=>{if(e.target===e.currentTarget && e.key==='Enter' && !disabled && await loadConversation(c.id)) onClose();}}
              onClick={async () => { if(!disabled && await loadConversation(c.id)) onClose(); }}
            >
              <span className="chat-hist-title">{c.title}</span>
              <button
                className="chat-hist-del"
                disabled={disabled}
                onClick={(e) => { e.stopPropagation(); if(window.confirm('이 대화를 KNU 서버에서 삭제할까요? 웹과 다른 기기에서도 삭제됩니다.')) deleteConversation(c.id); }}
                aria-label="대화 삭제"
              >
                <Icon name="trash" size={14} />
              </button>
            </div>
          ))}
          {historyCursor && <button className="chat-hist-new" disabled={disabled} onClick={()=>refreshConversations(true)}>이전 대화 더 보기</button>}
        </div>
      </aside>
    </>
  );
}
