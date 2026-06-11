import React, { useState } from "react";
import { Icon } from "../icons.jsx";
import { syncPortal, syncLms, INTEREST_KEYWORD_POOL, MAX_INTERESTS } from "../api.js";

/* 프로필/설정 — 포털 연결(동기화)로 학적 데이터 채움. */
export function SettingsPage({ user, onRefresh }) {
  const linked = !!user?.portal_linked;
  const [sid, setSid] = useState(user?.student_id || "");
  const [pw, setPw] = useState("");
  const [showPw, setShowPw] = useState(false);
  const [linking, setLinking] = useState(false);
  const [step, setStep] = useState("");
  const [err, setErr] = useState("");

  const [interests, setInterests] = useState(user?.interests?.slice() || []);
  const [savedKw, setSavedKw] = useState(user?.interests?.slice() || []);
  const dirty = JSON.stringify(interests) !== JSON.stringify(savedKw);

  async function doLink() {
    setErr("");
    if (!sid || !pw) { setErr("학번과 비밀번호를 입력해주세요."); return; }
    setLinking(true);
    try {
      // 포털 동기화 = 연결. 성공 시 학번이 계정에 링크되고 학적 데이터가 채워짐.
      await syncPortal(sid, pw, setStep);
      // LMS도 같은 자격증명으로 세션 발급(이후 비번 없이 재사용)
      try { await syncLms(sid, pw, setStep); } catch (_) { /* LMS 실패는 비치명 */ }
      setPw("");
      onRefresh?.();
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
  function save() {
    // TODO: 관심사 저장 엔드포인트 연결 (현재 로컬 상태만)
    setSavedKw(interests.slice());
  }

  const initial = (user?.name || "U").charAt(0);

  return (
    <div className="main-inner">
      <h1 className="page-title">프로필</h1>
      <p className="page-sub">계정 연동·학적·관심 키워드를 한곳에서 관리해요.</p>

      <div className="card profile-head">
        <div className="ph-avatar">{initial}</div>
        <div className="ph-info">
          <div className="ph-name">{user?.name || "학생"}</div>
          <div className="ph-meta">
            <span>{user?.major || "학과 미연동"}</span>
            {user?.year && <><span className="ph-dot">·</span><span>{user.year}학년</span></>}
            {user?.student_id && <><span className="ph-dot">·</span><span className="ph-sid">{user.student_id}</span></>}
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
              <div className="lb"><span className="lb-name">LMS</span><span className={user?.lms_linked ? "badge-link" : "badge-off"}>{user?.lms_linked ? <><Icon name="check" size={12} /> 연동됨</> : <><span className="dot-off"></span> 미연동</>}</span></div>
              <div className="lb"><span className="lb-name">포털</span><span className="badge-link"><Icon name="check" size={12} /> 연동됨</span></div>
            </div>
            <p className="caption" style={{ marginTop: 12 }}>공주대 통합 계정으로 연동되어 있어요. 비밀번호는 저장하지 않아요.</p>
            <button className="btn" style={{ marginTop: 14 }} onClick={() => setSid(user?.student_id || "")}>다시 동기화</button>
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
              <button className="btn-save" style={{ marginTop: 16 }} onClick={doLink} disabled={linking}>연동</button>
            </div>
            {linking && <div className="linking-row"><span className="spinner"></span> {step || "연동 중이에요..."}</div>}
          </>
        )}
      </div>

      {linked && (
        <div className="card set-card">
          <div className="set-h plain">학적 정보</div>
          <div className="record-grid">
            <div><div className="rec-k">이름</div><div className="rec-v">{user?.name}</div></div>
            <div><div className="rec-k">학번</div><div className="rec-v">{user?.student_id}</div></div>
            <div><div className="rec-k">학과</div><div className="rec-v">{user?.major}</div></div>
            <div><div className="rec-k">학년</div><div className="rec-v">{user?.year}학년</div></div>
          </div>
        </div>
      )}

      <div className="card set-card">
        <div className="kw-head">
          <div className="set-h plain">관심 키워드</div>
          <span className="kw-counter">{interests.length} / {MAX_INTERESTS}</span>
        </div>
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
          <button className="btn-save kw-save" onClick={save} disabled={!dirty}>
            <Icon name="check" size={15} /> 저장
          </button>
        </div>
      </div>
    </div>
  );
}
