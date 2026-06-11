import React, { useState, useEffect, useRef } from "react";
import { Icon } from "../icons.jsx";
import { streamChatbot, chatSuggestions } from "../api.js";
import { useApp } from "../store.jsx";

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
  const { profile, chatMsgs, setChatMsgs } = useApp();
  const [thinking, setThinking] = useState(false);
  const [status, setStatus] = useState("");
  const [input, setInput] = useState("");
  const scrollRef = useRef(null);

  useEffect(() => {
    if (scrollRef.current) scrollRef.current.scrollTop = scrollRef.current.scrollHeight;
  }, [chatMsgs, thinking, status]);

  async function send(text) {
    const q = (text ?? input).trim();
    if (!q || thinking) return;
    setChatMsgs((m) => [...m, { role: "user", content: q }]);
    setInput("");
    setThinking(true);
    setStatus("질문을 이해하고 있어요...");

    // 스트리밍될 빈 답변 버블을 미리 추가하고 토큰마다 갱신
    let idx = -1;
    setChatMsgs((m) => { idx = m.length; return [...m, { role: "assistant", answer: { intro: "", streaming: true } }]; });
    const update = (patch) =>
      setChatMsgs((m) => m.map((msg, i) => (i === idx ? { ...msg, answer: { ...msg.answer, ...patch } } : msg)));

    // 페이스드 리빌: 네트워크가 토큰을 버스트로 줘도 타이머로 한 글자씩 노출해
    // 항상 부드럽게 흐르게 한다. target=받은 전체, shown=화면에 보인 길이.
    let target = "";
    let shown = 0;
    let streamDone = false;
    const reveal = setInterval(() => {
      if (shown < target.length) {
        // 남은 양에 비례해 속도 가변(많이 밀리면 빨리 따라잡음)
        shown = Math.min(target.length, shown + Math.max(1, Math.ceil((target.length - shown) / 18)));
        update({ intro: target.slice(0, shown) });
      } else if (streamDone) {
        clearInterval(reveal);
        update({ intro: target, streaming: false });
      }
    }, 16);

    try {
      const final = await streamChatbot(q, profile?.major, {
        onStep: setStatus,
        onToken: (acc) => { target = acc; },
      });
      target = final.intro;
      streamDone = true;
      // outro는 리빌 완료 후 같이 반영되도록 보관
      const finishWatcher = setInterval(() => {
        if (shown >= target.length) { clearInterval(finishWatcher); update({ outro: final.outro }); }
      }, 16);
    } catch (e) {
      clearInterval(reveal);
      update({ intro: e.message, outro: "", streaming: false });
    } finally {
      setThinking(false);
      setStatus("");
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
            value={input}
            onChange={(e) => setInput(e.target.value)}
            onKeyDown={(e) => { if (e.key === "Enter" && !e.nativeEvent.isComposing) send(); }}
            placeholder="KNU에 대해 질문하기..."
          />
          <button className="send-btn" onClick={() => send()}><Icon name="send" size={17} /></button>
        </div>
        <div className="chat-disclaimer">KNU PICK은 실수할 수 있습니다. 중요한 학사 정보는 확인이 필요합니다.</div>
      </div>
    </div>
  );
}
