import React, { useState } from "react";
import { auth } from "./api.js";

export function Login({ onAuthed }) {
  const [mode, setMode] = useState("login");
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState("");

  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");

  const [email, setEmail] = useState("");
  const [codeSent, setCodeSent] = useState(false);
  const [code, setCode] = useState("");
  const [suName, setSuName] = useState("");
  const [suPw, setSuPw] = useState("");

  async function run(fn) {
    setErr(""); setBusy(true);
    try { await fn(); } catch (e) { setErr(e.message); } finally { setBusy(false); }
  }
  const doLogin = () => run(async () => { await auth.login(username, password); onAuthed(); });
  const sendCode = () => run(async () => { await auth.signupRequest(email); setCodeSent(true); });
  const doSignup = () => run(async () => { await auth.signupVerify(email, code, suName, suPw); onAuthed(); });

  return (
    <div className="auth-wrap">
      <div className="card auth-card">
        <div className="auth-brand">
          <div>
            <div className="brand-name" style={{ fontSize: 22 }}>KNU PICK</div>
            <div className="brand-sub">Academic Intelligence</div>
          </div>
        </div>

        {mode === "login" ? (
          <>
            <h1 className="page-title" style={{ fontSize: 24, marginBottom: 20 }}>로그인</h1>
            <label className="field-label">아이디</label>
            <input className="field-input" value={username} onChange={(e) => setUsername(e.target.value)} />
            <label className="field-label" style={{ marginTop: 14 }}>비밀번호</label>
            <input className="field-input" type="password" value={password} onChange={(e) => setPassword(e.target.value)} onKeyDown={(e) => e.key === "Enter" && doLogin()} />
            {err && <div className="auth-err">{err}</div>}
            <button className="btn btn-primary" style={{ width: "100%", marginTop: 18 }} onClick={doLogin} disabled={busy}>{busy ? "로그인 중..." : "로그인"}</button>
            <button className="link-btn" onClick={() => { setMode("signup"); setErr(""); }}>학교 메일로 가입하기</button>
          </>
        ) : (
          <>
            <h1 className="page-title" style={{ fontSize: 24, marginBottom: 20 }}>회원가입</h1>
            <label className="field-label">학교 메일 (@smail.kongju.ac.kr)</label>
            <input className="field-input" value={email} onChange={(e) => setEmail(e.target.value)} placeholder="hong@smail.kongju.ac.kr" />
            {!codeSent ? (
              <button className="btn" style={{ width: "100%", marginTop: 14 }} onClick={sendCode} disabled={busy}>{busy ? "발송 중..." : "인증 코드 받기"}</button>
            ) : (
              <>
                <label className="field-label" style={{ marginTop: 14 }}>인증 코드 (메일·스팸함 확인)</label>
                <input className="field-input" value={code} onChange={(e) => setCode(e.target.value)} maxLength={6} />
                <label className="field-label" style={{ marginTop: 14 }}>아이디</label>
                <input className="field-input" value={suName} onChange={(e) => setSuName(e.target.value)} />
                <label className="field-label" style={{ marginTop: 14 }}>비밀번호 (8자 이상)</label>
                <input className="field-input" type="password" value={suPw} onChange={(e) => setSuPw(e.target.value)} />
                <button className="btn btn-primary" style={{ width: "100%", marginTop: 18 }} onClick={doSignup} disabled={busy}>{busy ? "가입 중..." : "가입 완료"}</button>
              </>
            )}
            {err && <div className="auth-err">{err}</div>}
            <button className="link-btn" onClick={() => { setMode("login"); setErr(""); }}>이미 계정이 있어요</button>
          </>
        )}
      </div>
    </div>
  );
}
