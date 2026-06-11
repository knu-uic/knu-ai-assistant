import React, { useState, useEffect, useRef } from "react";
import { Icon } from "../icons.jsx";
import { askChatbot, chatSuggestions } from "../api.js";
import { useApp } from "../store.jsx";

function AnswerCard({ a }) {
  return (
    <div className="bot-msg">
      <div className="bot-ico"><Icon name="bot" size={17} /></div>
      <div className="bot-bubble">
        <p className="ans-intro" style={{ whiteSpace: "pre-wrap" }}>{a.intro}</p>
        {a.outro && <p className="ans-outro">{a.outro}</p>}
      </div>
    </div>
  );
}

export function ChatbotPage() {
  const { profile, chatMsgs, setChatMsgs } = useApp();
  const [thinking, setThinking] = useState(false);
  const [input, setInput] = useState("");
  const scrollRef = useRef(null);

  useEffect(() => {
    if (scrollRef.current) scrollRef.current.scrollTop = scrollRef.current.scrollHeight;
  }, [chatMsgs, thinking]);

  async function send(text) {
    const q = (text ?? input).trim();
    if (!q || thinking) return;
    setChatMsgs((m) => [...m, { role: "user", content: q }]);
    setInput("");
    setThinking(true);
    try {
      const answer = await askChatbot(q, profile?.major);
      setChatMsgs((m) => [...m, { role: "assistant", answer }]);
    } catch (e) {
      setChatMsgs((m) => [...m, { role: "assistant", answer: { intro: e.message, outro: "" } }]);
    } finally {
      setThinking(false);
    }
  }

  const empty = chatMsgs.length === 0 && !thinking;

  return (
    <div className="chat-wrap">
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
          {chatMsgs.map((m, i) =>
            m.role === "user"
              ? <div key={i} className="user-msg">{m.content}</div>
              : <AnswerCard key={i} a={m.answer} />
          )}
          {thinking && (
            <div className="thinking-chip"><span className="spinner"></span> 답변을 생성하고 있어요...</div>
          )}
        </div>
      </div>

      <div className="chat-input-area">
        <div className="chat-input">
          <input
            value={input}
            onChange={(e) => setInput(e.target.value)}
            onKeyDown={(e) => { if (e.key === "Enter") send(); }}
            placeholder="KNU에 대해 질문하기..."
          />
          <button className="send-btn" onClick={() => send()}><Icon name="send" size={17} /></button>
        </div>
        <div className="chat-disclaimer">KNU PICK은 실수할 수 있습니다. 중요한 학사 정보는 확인이 필요합니다.</div>
      </div>
    </div>
  );
}
