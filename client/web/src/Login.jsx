import React, { useState } from "react";
import { Crest } from "./icons.jsx";
import { auth } from "./api.js";

export function Login({ onAuthed }) {
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState("");

  const [studentId, setStudentId] = useState("");
  const [password, setPassword] = useState("");

  async function run(fn) {
    setErr(""); setBusy(true);
    try { await fn(); } catch (e) { setErr(e.message); } finally { setBusy(false); }
  }
  const doLogin = () => run(async () => { await auth.portalLogin(studentId, password); onAuthed(); });

  return (
    <div className="auth-wrap">
      <div className="card auth-card">
        <div className="auth-brand">
          <Crest size={46} />
          <div>
            <div className="brand-name" style={{ fontSize: 22 }}>KNU PICK</div>
            <div className="brand-sub">Academic Intelligence</div>
          </div>
        </div>

        <>
            <h1 className="page-title" style={{ fontSize: 24, marginBottom: 8 }}>학교 계정 로그인</h1>
            <p style={{ marginTop: 0, marginBottom: 20 }}>공주대 포털에서 사용하는 학번과 비밀번호를 입력하세요.</p>
            <label className="field-label">학번</label>
            <input className="field-input" value={studentId} onChange={(e) => setStudentId(e.target.value)} inputMode="numeric" autoComplete="username" />
            <label className="field-label" style={{ marginTop: 14 }}>비밀번호</label>
            <input className="field-input" type="password" value={password} onChange={(e) => setPassword(e.target.value)} onKeyDown={(e) => e.key === "Enter" && doLogin()} autoComplete="current-password" />
            {err && <div className="auth-err">{err}</div>}
            <button className="btn btn-primary" style={{ width: "100%", marginTop: 18 }} onClick={doLogin} disabled={busy}>{busy ? "로그인 중..." : "로그인"}</button>
        </>
      </div>
    </div>
  );
}
