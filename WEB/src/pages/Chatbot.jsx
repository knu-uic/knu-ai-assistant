import React, { useState, useEffect, useRef } from "react";
import { Icon } from "../icons.jsx";
import { askChatbot, chatSuggestions } from "../api.js";

function AnswerCard({ a }) {
  const [open, setOpen] = useState(false);
  return (
    <div className="bot-msg">
      <div className="bot-ico"><Icon name="bot" size={17} /></div>
      <div className="bot-bubble">
        <p className="ans-intro">{a.intro}</p>
        {a.bullets.length > 0 && (
          <ul className="ans-list">
            {a.bullets.map(([h, t], i) => (
              <li key={i}><strong>{h}:</strong> {t}</li>
            ))}
          </ul>
        )}
        {a.outro && <p className="ans-outro">{a.outro}</p>}
        {a.citations.length > 0 && (
          <>
            <button className={"cite-toggle" + (open ? " open" : "")} onClick={() => setOpen(!open)}>
              <Icon name="citation" size={14} />
              <span>출처 ({a.citations.length})</span>
              <Icon name="chevron" size={14} />
            </button>
            {open && (
              <div className="cite-list">
                {a.citations.map((c, i) => (
                  <a key={i} className="cite-item" href={c.url}>
                    <Icon name="fileText" size={14} /> {c.title}
                  </a>
                ))}
              </div>
            )}
          </>
        )}
      </div>
    </div>
  );
}

export function ChatbotPage({ user }) {
  const [msgs, setMsgs] = useState([]);
  const [thinking, setThinking] = useState(false);
  const [input, setInput] = useState("");
  const scrollRef = useRef(null);

  useEffect(() => {
    if (scrollRef.current) scrollRef.current.scrollTop = scrollRef.current.scrollHeight;
  }, [msgs, thinking]);

  async function send(text) {
    const q = (text ?? input).trim();
    if (!q || thinking) return;
    setMsgs((m) => [...m, { role: "user", content: q }]);
    setInput("");
    setThinking(true);
    try {
      const answer = await askChatbot(q, user?.major);
      setMsgs((m) => [...m, { role: "assistant", answer }]);
    } catch (e) {
      setMsgs((m) => [...m, { role: "assistant", answer: { intro: e.message, bullets: [], outro: "", citations: [] } }]);
    } finally {
      setThinking(false);
    }
  }

  const empty = msgs.length === 0 && !thinking;

  return (
    <div className="chat-wrap">
      <div className="chat-quick">
        {chatSuggestions.map((s) => (
          <button key={s.label} className="quick-chip" onClick={() => send(s.label)}>
            <Icon name={s.icon} size={15} /> {s.label}
          </button>
        ))}
      </div>

      <div className="chat-scroll" ref={scrollRef}>
        {empty && (
          <div className="chat-welcome">
            <div className="welcome-ico"><Icon name="bot" size={26} /></div>
            <div className="welcome-title">무엇을 도와드릴까요?</div>
            <div className="welcome-sub">KNU 학사·캠퍼스·규정에 대해 무엇이든 물어보세요.</div>
          </div>
        )}

        <div className="chat-msgs">
          {msgs.map((m, i) =>
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
          <button className="attach-btn"><Icon name="paperclip" size={18} /></button>
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
