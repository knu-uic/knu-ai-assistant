import React, { useState, useEffect, useRef } from "react";
import { Icon } from "../icons.jsx";
import { chatSuggestions, chatModels } from "../api.js";
import { useApp } from "../store.jsx";
import { ChatHistory } from "./ChatHistory.jsx";

// [텍스트](url)·맨 URL을 클릭 가능한 링크로. 나머지는 평문(줄바꿈은 pre-wrap).
const LINK_RE = /\[([^\]]+)\]\((https?:\/\/[^\s)]+)\)|(https?:\/\/[^\s)]+)/g;
function linkify(text) {
  const out = [];
  let last = 0, m, k = 0;
  while ((m = LINK_RE.exec(text)) !== null) {
    if (m.index > last) out.push(text.slice(last, m.index));
    const label = m[1] || m[3];
    const href = m[2] || m[3];
    out.push(<a key={k++} href={href} target="_blank" rel="noreferrer">{label}</a>);
    last = m.index + m[0].length;
  }
  if (last < text.length) out.push(text.slice(last));
  return out;
}

function AnswerCard({ a }) {
  return (
    <div className="bot-msg">
      <div className="bot-ico"><Icon name="bot" size={17} /></div>
      <div className="bot-bubble">
        <p className="ans-intro" style={{ whiteSpace: "pre-wrap" }}>
          {linkify(a.intro)}
          {a.streaming && <span className="stream-caret" />}
        </p>
        {a.outro && <p className="ans-outro">{a.outro}</p>}
      </div>
    </div>
  );
}

export function ChatbotPage() {
  const { chatMsgs, sendConversation, chatGenerating: thinking, historyBusy, historyError, historyNotice,
    chatSource: source, chooseChatSource: chooseSource } = useApp();
  const [status, setStatus] = useState("");
  const [input, setInput] = useState("");
  const [panelOpen, setPanelOpen] = useState(false);  // 대화목록 패널 기본 접힘
  const [schoolModel, setSchoolModel] = useState(null);
  const scrollRef = useRef(null);

  useEffect(() => {
    let active = true;
    chatModels().then((result) => { if (active) setSchoolModel(result.school); })
      .catch(() => { if (active) setSchoolModel({ available: false, model: "" }); });
    return () => { active = false; };
  }, []);

  useEffect(() => {
    if (scrollRef.current) scrollRef.current.scrollTop = scrollRef.current.scrollHeight;
  }, [chatMsgs, thinking, status]);

  async function send(text) {
    const q = (text ?? input).trim();
    if (!q || thinking || historyBusy) return;
    if(q.length>10000) { setStatus("질문은 10,000자 이하로 입력해주세요."); return; }
    setStatus("질문을 이해하고 있어요...");
    setInput("");
    const success = await sendConversation(q, {onStep:setStatus});
    if(!success) setInput(q);
    setStatus("");
  }

  const empty = chatMsgs.length === 0 && !thinking;

  return (
    <div className="chat-wrap">
      <label className="chat-model-picker">대화 모델
        <select value={source} disabled={thinking || historyBusy} onChange={(e) => chooseSource(e.target.value)}>
          <option value="personal">내 모델</option>
          <option value="school" disabled={!schoolModel?.available}>
            {schoolModel?.available ? `학교 제공 · ${schoolModel.model}` : "학교 제공 · 미설정"}
          </option>
        </select>
      </label>
      <button className="chat-hist-toggle" onClick={() => setPanelOpen(true)} aria-label="대화 목록 열기">
        <Icon name="menu" size={20} />
      </button>
      <ChatHistory open={panelOpen} onClose={() => setPanelOpen(false)} />
      {(historyError || historyNotice) && <div role="status" className="chat-history-feedback">{historyError || historyNotice}</div>}
      <div className="chat-scroll" ref={scrollRef}>
        {empty && (
          <div className="chat-welcome">
            <div className="welcome-ico"><Icon name="bot" size={26} /></div>
            <div className="welcome-title">무엇을 도와드릴까요?</div>
            <div className="welcome-sub">KNU 학사·캠퍼스·규정에 대해 무엇이든 물어보세요.</div>
            <div className="welcome-chips">
              {chatSuggestions.map((s) => (
                <button key={s.label} className="quick-chip" onClick={() => send(s.label)}>
                  <Icon name={s.icon} size={15} /> {s.label}
                </button>
              ))}
            </div>
          </div>
        )}
        <div className="chat-msgs">
          {chatMsgs.map((m, i) => {
            if (m.role === "user") return <div key={i} className="user-msg">{m.content}</div>;
            // 토큰 도착 전 빈 답변 버블은 숨김 — 진행 상태칩이 그 구간을 대신 표시
            if (m.answer.streaming && !m.answer.intro) return null;
            return <AnswerCard key={i} a={m.answer} />;
          })}
          {thinking && status && (
            <div className="thinking-chip"><span className="spinner"></span> {status}</div>
          )}
        </div>
      </div>

      <div className="chat-input-area">
        <div className="chat-input">
          <input
            disabled={thinking || historyBusy}
            maxLength={10000}
            value={input}
            onChange={(e) => setInput(e.target.value)}
            onKeyDown={(e) => { if (e.key === "Enter" && !e.nativeEvent.isComposing) send(); }}
            placeholder="KNU에 대해 질문하기..."
          />
          <button className="send-btn" disabled={thinking || historyBusy} onClick={() => send()}><Icon name="send" size={17} /></button>
        </div>
        <div className="chat-disclaimer">KNU PICK은 실수할 수 있습니다. 중요한 학사 정보는 확인이 필요합니다.</div>
      </div>
    </div>
  );
}
