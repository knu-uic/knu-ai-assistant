import React, { useEffect } from "react";
import { Icon } from "../icons.jsx";
import { useApp } from "../store.jsx";
import { weekGrid } from "../timetable.js";

function WeekTimetable({ timetable }) {
  const grid = weekGrid(timetable);
  if (!grid || grid.rows.length === 0) return null;
  return (
    <>
      <h2 className="sub-h"><Icon name="calendar" size={19} /> 주간 시간표</h2>
      <div className="card" style={{ marginTop: 10, padding: 10 }}>
        <table className="week-grid">
          <colgroup>
            <col style={{ width: "64px" }} />
            {grid.days.map((_, i) => <col key={i} style={{ width: `${100 / grid.days.length}%` }} />)}
          </colgroup>
          <thead><tr><th>교시</th>{grid.days.map((d) => <th key={d}>{d}</th>)}</tr></thead>
          <tbody>
            {grid.rows.map((row, ri) => (
              <tr key={ri}>
                <td className="wperiod"><div className="wp-no">{row.no}</div><div className="wp-time">{row.time}</div></td>
                {row.cells.map((cell, ci) => (
                  <td key={ci}>{cell ? <div className="wcell">{cell}</div> : null}</td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </>
  );
}

const GRAD_PATHS = [
  ["교양", "기초교양", "필수"], ["교양", "기초교양", "선택"], ["교양", "균형교양", "선택"],
  ["교양", "소양교양", "필수"], ["교양", "소양교양", "선택"], ["교양", "계"],
  ["전공", "최소전공인정학점", "전공기초"], ["전공", "최소전공인정학점", "콜라주"],
  ["전공", "최소전공인정학점", "전공핵심"], ["전공", "최소전공인정학점", "소계"],
  ["전공", "전공심화"], ["전공", "계"], ["교직"], ["융합탐색"],
  ["복수전공", "기초"], ["복수전공", "필수"], ["복수전공", "선택"],
  ["부전공", "필수"], ["부전공", "선택"], ["졸업학점계"],
  ["콜라주", "자과"], ["콜라주", "타과"],
];
const SUBTOTAL_COLS = new Set([5, 9, 11, 19]);

function dig(obj, path) {
  let cur = obj;
  for (const k of path) {
    if (!cur || typeof cur !== "object") return null;
    cur = cur[k];
  }
  return cur;
}

function toGrid(graduationCredits) {
  if (!graduationCredits) return null;
  const standards = [], taken = [], deficit = [];
  for (const path of GRAD_PATHS) {
    const cell = dig(graduationCredits, path) || {};
    const std = parseFloat(cell["기준"] ?? "0") || 0;
    const tkn = parseFloat(cell["취득"] ?? "0") || 0;
    standards.push(String(cell["기준"] ?? "0"));
    taken.push(String(cell["취득"] ?? "0"));
    deficit.push(String(Math.max(0, std - tkn)));
  }
  return { subtotalCols: [...SUBTOTAL_COLS], standards, taken, deficit };
}

function CreditTable({ grid }) {
  const sub = new Set(grid.subtotalCols || []);
  const cell = (v, kind, i) => {
    const isSub = sub.has(i);
    if (kind === "deficit") {
      const need = v !== "0" && v !== "-" && v !== "";
      return <td key={i} className={"gc " + (need ? "need" : "done") + (isSub ? " sub" : "")}>{need ? v : "-"}</td>;
    }
    return <td key={i} className={"gc" + (isSub ? " sub" : "")}>{v}</td>;
  };
  return (
    <div className="grad-scroll">
      <table className="grad-table">
        <thead>
          <tr>
            <th rowSpan="3">구 분</th><th colSpan="6">교 양</th><th colSpan="6">전 공</th>
            <th rowSpan="3">교직</th><th rowSpan="3">융합<br/>탐색</th><th colSpan="3">복수전공</th>
            <th colSpan="2">부전공</th><th rowSpan="3">졸업<br/>학점계</th><th colSpan="2">콜라주</th>
          </tr>
          <tr>
            <th colSpan="2">기초교양</th><th rowSpan="2">균형<br/>교양</th><th colSpan="2">소양교양</th>
            <th rowSpan="2">소계</th><th colSpan="4">최소전공인정학점</th><th rowSpan="2">전공<br/>심화</th>
            <th rowSpan="2">계</th><th rowSpan="2">기초</th><th rowSpan="2">필수</th><th rowSpan="2">선택</th>
            <th rowSpan="2">필수</th><th rowSpan="2">선택</th><th rowSpan="2">자과</th><th rowSpan="2">타과</th>
          </tr>
          <tr>
            <th>필수</th><th>선택</th><th>필수</th><th>선택</th>
            <th>전공<br/>기초</th><th>콜라주</th><th>전공<br/>핵심</th><th>소계</th>
          </tr>
        </thead>
        <tbody>
          <tr><td className="rh">기준학점</td>{grid.standards.map((v, i) => cell(v, "std", i))}</tr>
          <tr><td className="rh">취득학점</td>{grid.taken.map((v, i) => cell(v, "tkn", i))}</tr>
          <tr><td className="rh">부족학점</td>{grid.deficit.map((v, i) => cell(v, "deficit", i))}</tr>
        </tbody>
      </table>
    </div>
  );
}

function GenericGrids({ data }) {
  const grids = data?.grids || {};
  const entries = Object.entries(grids);
  if (entries.length === 0) return null;
  return entries.map(([gid, g]) => (
    <div key={gid} style={{ marginTop: 18 }}>
      {g.title && <div className="table-label">{g.title}</div>}
      <div className="card flush">
        <div className="grad-scroll">
          <table className="data-table">
            <thead><tr>{(g.columns || []).map((c, i) => <th key={i}>{c}</th>)}</tr></thead>
            <tbody>
              {(g.rows || []).map((row, ri) => (
                <tr key={ri}>{row.map((v, ci) => <td key={ci}>{v}</td>)}</tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  ));
}

export function PortalPage() {
  const { profile, portalData, loadPortal, timetable, loadTimetable } = useApp();
  useEffect(() => { loadPortal(); loadTimetable(); }, [loadPortal, loadTimetable]);

  const grid = toGrid(portalData?.graduation_credits);
  const linked = !!profile?.portal_linked;

  return (
    <div className="main-inner portal-wide">
      <div className="row-between" style={{ alignItems: "flex-start" }}>
        <div>
          <h1 className="page-title">포털</h1>
          <p className="page-sub">통합정보시스템(KNUIS)에서 연동된 시간표·취득학점·성적 정보입니다.</p>
        </div>
      </div>

      {portalData && !linked && (
        <div className="banner" style={{ marginTop: 20 }}>설정에서 포털을 연결하면 시간표·취득학점·성적이 표시됩니다.</div>
      )}

      <WeekTimetable timetable={timetable} />

      {grid && (
        <>
          <h2 className="sub-h" style={{ marginTop: 32 }}><Icon name="cap" size={19} /> 취득학점 현황</h2>
          <p className="caption" style={{ marginTop: -4, marginBottom: 12 }}>동기화된 졸업사전예고 취득학점 상세 현황입니다. (가로 스크롤 가능)</p>
          <div className="card flush"><CreditTable grid={grid} /></div>
        </>
      )}

      {portalData?.grade_distribution && (
        <>
          <h2 className="sub-h" style={{ marginTop: 32 }}><Icon name="bars" size={19} /> 나의 성적분포</h2>
          <GenericGrids data={portalData.grade_distribution} />
        </>
      )}

      {portalData?.cumulative_grades && (
        <>
          <h2 className="sub-h" style={{ marginTop: 34 }}><Icon name="book" size={19} /> 누적 성적</h2>
          <GenericGrids data={portalData.cumulative_grades} />
        </>
      )}
    </div>
  );
}
