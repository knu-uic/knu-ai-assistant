import React, { useState, useEffect } from "react";
import { Icon } from "../icons.jsx";
import { INTEREST_KEYWORD_POOL, MAX_INTERESTS, llmAccounts } from "../api.js";
import { useApp } from "../store.jsx";

export function SettingsPage() {
  const { profile, logout, saveInterests, syncPortal, syncLms } = useApp();
  const linked = !!profile?.portal_linked;

  const [sid, setSid] = useState(profile?.student_id || "");
  const [pw, setPw] = useState("");
  const [showPw, setShowPw] = useState(false);
  const [linking, setLinking] = useState(false);
  const [step, setStep] = useState("");
  const [err, setErr] = useState("");

  // 관심사: 프로필이 갱신되면 동기화
  const [interests, setInterests] = useState(profile?.interests || []);
  const [saving, setSaving] = useState(false);
  const [toast, setToast] = useState("");
  const [accounts, setAccounts] = useState([]);
  const [llmError, setLlmError] = useState("");
  const [llmBusy, setLlmBusy] = useState(false);
  const [apiKey, setApiKey] = useState("");
  const [geminiKey, setGeminiKey] = useState("");
  const [login, setLogin] = useState(null);
  const [models, setModels] = useState({});
  const [selectedModels, setSelectedModels] = useState({});
  async function reloadAccounts() {
    const result = await llmAccounts.list();
    setAccounts(result.items || []);
  }
  useEffect(() => { reloadAccounts().catch((e) => setLlmError(e.message)); }, []);
  useEffect(() => {
    if (!login?.id) return;
    let cancelled = false;
    const timer = setInterval(async () => {
      try {
        const status = await llmAccounts.pollCodexLogin(login.id);
        if (cancelled) return;
        if (status.status === "approved") {
          setLogin(null);
          await reloadAccounts();
          setToast("Codex 계정이 연결됐어요. 사용할 모델을 선택해주세요.");
        } else if (status.status === "expired") {
          setLogin(null);
          setLlmError("로그인 시간이 만료됐습니다. 다시 시도해주세요.");
        }
      } catch (e) {
        if (!cancelled) { setLogin(null); setLlmError(e.message); }
      }
    }, Math.max(3000, (login.interval || 5) * 1000));
    return () => { cancelled = true; clearInterval(timer); };
  }, [login?.id]);

  async function connectApiKey() {
    setLlmBusy(true); setLlmError("");
    try { await llmAccounts.addOpenAIKey(apiKey); setApiKey(""); await reloadAccounts(); }
    catch (e) { setLlmError(e.message); }
    finally { setLlmBusy(false); }
  }
  async function connectGeminiKey() {
    setLlmBusy(true); setLlmError("");
    try { await llmAccounts.addGeminiKey(geminiKey); setGeminiKey(""); await reloadAccounts(); }
    catch (e) { setLlmError(e.message); }
    finally { setLlmBusy(false); }
  }
  async function connectCodex() {
    setLlmBusy(true); setLlmError("");
    try { setLogin(await llmAccounts.startCodexLogin()); }
    catch (e) { setLlmError(e.message); }
    finally { setLlmBusy(false); }
  }
  async function loadModels(id) {
    setLlmError("");
    try {
      const result = await llmAccounts.models(id);
      setModels((current) => ({ ...current, [id]: result.models || [] }));
    } catch (e) { setLlmError(e.message); }
  }
  async function chooseModel(id) {
    setLlmError("");
    try {
      const account = accounts.find((item) => item.id === id);
      await llmAccounts.select(id, selectedModels[id] || account?.model);
      await reloadAccounts();
    }
    catch (e) { setLlmError(e.message); }
  }
  async function removeLlmAccount(id) {
    if (!window.confirm("이 개인 LLM 계정 연결을 해제할까요?")) return;
    try { await llmAccounts.remove(id); await reloadAccounts(); }
    catch (e) { setLlmError(e.message); }
  }
  useEffect(() => { setInterests(profile?.interests || []); }, [profile]);
  const dirty = JSON.stringify(interests) !== JSON.stringify(profile?.interests || []);

  async function doLink() {
    setErr("");
    if (!sid || !pw) { setErr("학번과 비밀번호를 입력해주세요."); return; }
    setLinking(true);
    try {
      await syncPortal(sid, pw, setStep);
      try { await syncLms(sid, pw, setStep); } catch (_) { /* LMS 실패는 비치명 */ }
      setPw("");
    } catch (e) {
      setErr(e.message);
    } finally {
      setLinking(false);
      setStep("");
    }
  }

  function toggleKw(kw) {
    setInterests((cur) => {
      if (cur.includes(kw)) return cur.filter((k) => k !== kw);
      if (cur.length >= MAX_INTERESTS) return cur;
      return [...cur, kw];
    });
  }
  async function save() {
    setSaving(true);
    try {
      await saveInterests(interests);
      setToast("관심 키워드가 저장됐어요.");
      setTimeout(() => setToast(""), 2200);
    } catch (e) {
      setToast(e.message);
      setTimeout(() => setToast(""), 3000);
    } finally {
      setSaving(false);
    }
  }

  const initial = (profile?.name || "U").charAt(0);

  return (
    <div className="main-inner">
      <h1 className="page-title">프로필</h1>
      <p className="page-sub">계정 연동·학적·관심 키워드를 한곳에서 관리해요.</p>

      <div className="card profile-head">
        <div className="ph-avatar">{initial}</div>
        <div className="ph-info">
          <div className="ph-name">{profile?.name || "학생"}</div>
          <div className="ph-meta">
            <span>{profile?.major || "학과 미연동"}</span>
            {profile?.year != null && <><span className="ph-dot">·</span><span>{profile.year}학년</span></>}
            {profile?.student_id && <><span className="ph-dot">·</span><span className="ph-sid">{profile.student_id}</span></>}
          </div>
        </div>
        {linked
          ? <span className="badge-link"><Icon name="check" size={12} /> 연동됨</span>
          : <span className="badge-off"><span className="dot-off"></span> 미연동</span>}
      </div>

      <div className="card set-card">
        <div className="set-h"><Icon name="link" size={17} /> 계정 연동</div>
        {linked ? (
          <>
            <div className="link-badges">
              <div className="lb"><span className="lb-name">LMS</span><span className={profile?.lms_linked ? "badge-link" : "badge-off"}>{profile?.lms_linked ? <><Icon name="check" size={12} /> 연동됨</> : <><span className="dot-off"></span> 미연동</>}</span></div>
              <div className="lb"><span className="lb-name">포털</span><span className="badge-link"><Icon name="check" size={12} /> 연동됨</span></div>
            </div>
            <p className="caption" style={{ marginTop: 12 }}>공주대 통합 계정으로 연동되어 있어요. 비밀번호는 저장하지 않아요.</p>
          </>
        ) : (
          <>
            <p className="caption" style={{ marginTop: 4 }}>공주대 통합 계정(LMS·포털 동일)으로 연결하면 학적·성적·과제가 채워집니다. 비밀번호는 저장하지 않아요.</p>
            <div className="link-form">
              <label className="field-label">학번</label>
              <input className="field-input" value={sid} onChange={(e) => setSid(e.target.value)} />
              <label className="field-label" style={{ marginTop: 14 }}>비밀번호</label>
              <div className="pw-wrap">
                <input className="field-input" type={showPw ? "text" : "password"} value={pw} onChange={(e) => setPw(e.target.value)} />
                <button className="pw-eye" onClick={() => setShowPw(!showPw)}><Icon name="eye" size={16} /></button>
              </div>
              {err && <div className="auth-err">{err}</div>}
              <button className="btn-save" style={{ marginTop: 16 }} onClick={doLink} disabled={linking}>{linking ? (step || "연동 중...") : "연동"}</button>
            </div>
            {linking && <div className="linking-row"><span className="spinner"></span> {step || "연동 중이에요... (수십 초 소요)"}</div>}
          </>
        )}
      </div>

      <div className="card set-card">
        <div className="set-h plain">대화용 개인 AI 계정</div>
        <p className="caption">여기서 연결한 계정은 본인의 웹 대화에만 사용됩니다. 학교의 공지 수집·정제 계정과 별개입니다.</p>
        {accounts.map((account) => (
          <div key={account.id} className="link-badges" style={{ marginTop: 14, display: "block" }}>
            <strong>{account.label}</strong> <span className="caption">({account.provider === "openai" ? "OpenAI API" : account.provider === "google" ? "Gemini API" : "Codex"})</span>
            {account.active && account.model && <span className="badge-link" style={{ marginLeft: 8 }}>사용 중 · {account.model}</span>}
            <div className="link-form" style={{ marginTop: 10 }}>
              <button className="btn-save" onClick={() => loadModels(account.id)}>모델 목록</button>
              {(models[account.id] || []).length > 0 && <>
                <select className="field-input" value={selectedModels[account.id] || account.model || ""}
                  onChange={(e) => setSelectedModels((current) => ({ ...current, [account.id]: e.target.value }))}>
                  <option value="">모델 선택</option>
                  {models[account.id].map((model) => <option key={model} value={model}>{model}</option>)}
                </select>
                <button className="btn-save" disabled={!selectedModels[account.id] && !account.model}
                  onClick={() => chooseModel(account.id)}>대화 모델로 사용</button>
              </>}
              <button className="btn" onClick={() => removeLlmAccount(account.id)}>연결 해제</button>
            </div>
          </div>
        ))}
        <div className="link-form" style={{ marginTop: 18 }}>
          <label className="field-label">OpenAI API 키 연결</label>
          <input className="field-input" type="password" autoComplete="new-password" value={apiKey}
            onChange={(e) => setApiKey(e.target.value)} placeholder="sk-..." />
          <button className="btn-save" disabled={!apiKey || llmBusy} onClick={connectApiKey}>API 키 저장</button>
          <button className="btn-save" disabled={llmBusy || !!login} onClick={connectCodex}>Codex 계정으로 로그인</button>
        </div>
        <div className="link-form" style={{ marginTop: 12 }}>
          <label className="field-label">Gemini API 키 연결</label>
          <input className="field-input" type="password" autoComplete="new-password" value={geminiKey}
            onChange={(e) => setGeminiKey(e.target.value)} placeholder="Gemini API 키" />
          <button className="btn-save" disabled={!geminiKey || llmBusy} onClick={connectGeminiKey}>API 키 저장</button>
        </div>
        {login && <p className="caption" style={{ marginTop: 12 }}>
          <a href={login.verification_url} target="_blank" rel="noreferrer">Codex 인증 페이지 열기</a>에서 코드 <strong>{login.user_code}</strong>를 입력하세요. 연결 상태를 확인하고 있습니다.
        </p>}
        {llmError && <div className="auth-err">{llmError}</div>}
      </div>

      {linked && (
        <div className="card set-card">
          <div className="set-h plain">학적 정보</div>
          <div className="record-grid">
            <div><div className="rec-k">이름</div><div className="rec-v">{profile?.name}</div></div>
            <div><div className="rec-k">학번</div><div className="rec-v">{profile?.student_id}</div></div>
            <div><div className="rec-k">학과</div><div className="rec-v">{profile?.major}</div></div>
            <div><div className="rec-k">학년</div><div className="rec-v">{profile?.year}학년</div></div>
          </div>
        </div>
      )}

      <div className="card set-card">
        <div className="kw-head">
          <div className="set-h plain">관심 키워드</div>
          <span className="kw-counter">{interests.length} / {MAX_INTERESTS}</span>
        </div>
        {!linked && <p className="caption" style={{ marginTop: 2 }}>포털을 연결하면 관심 키워드를 저장할 수 있어요.</p>}
        <div className="kw-grid">
          {INTEREST_KEYWORD_POOL.map((kw) => {
            const on = interests.includes(kw);
            const full = !on && interests.length >= MAX_INTERESTS;
            return (
              <button key={kw} className={"kw-pill" + (on ? " on" : "") + (full ? " disabled" : "")} disabled={full} onClick={() => toggleKw(kw)}>
                {on && <Icon name="check" size={13} style={{ marginRight: 5 }} />}{kw}
              </button>
            );
          })}
        </div>
        <div className="kw-foot">
          <span className="caption">{dirty ? "변경사항이 저장되지 않았어요." : "최신 상태예요."}</span>
          <button className="btn-save kw-save" onClick={save} disabled={!dirty || saving || !linked}>
            <Icon name="check" size={15} /> {saving ? "저장 중..." : "저장"}
          </button>
        </div>
      </div>

      <button className="btn" style={{ marginTop: 4 }} onClick={logout}>로그아웃</button>

      {toast && <div className="toast"><Icon name="check" size={15} /> {toast}</div>}
    </div>
  );
}
