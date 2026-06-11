/* 포털 시간표 데이터 변환.
   원본: [{ rows: [["교시","월요일",...,"토요일"], [periodRaw, cell, ...], ...] }]
   periodRaw 예: "1교시 주간: (09:00~09:50)" (멀티라인·야간 포함 가능). */

const DAY_CHARS = ["일", "월", "화", "수", "목", "금", "토"];
const WEEKDAYS = ["월", "화", "수", "목", "금"]; // 주말 제외

function firstRows(timetable) {
  if (!Array.isArray(timetable) || timetable.length === 0) return null;
  const rows = timetable[0]?.rows;
  if (!Array.isArray(rows) || rows.length < 2) return null;
  return rows;
}

/* "1교시 주간: (09:00~09:50)" → { no: "1교시", time: "09:00~09:50" } */
function parsePeriod(raw) {
  const s = String(raw || "");
  const no = (s.match(/(\d+)\s*교시/) || [])[1];
  const time = (s.match(/(\d{1,2}:\d{2}\s*~\s*\d{1,2}:\d{2})/) || [])[1];
  return { no: no ? `${no}교시` : s.trim(), time: (time || "").replace(/\s/g, "") };
}

/* 평일 컬럼 인덱스만: [{idx, label}] (월~금) */
function weekdayCols(header) {
  const cols = [];
  for (let i = 1; i < header.length; i++) {
    const h = String(header[i]);
    if (WEEKDAYS.some((d) => h.includes(d))) cols.push({ idx: i, label: h.replace("요일", "") });
  }
  return cols;
}

/* 주간 격자: { days:["월",...], rows:[{no,time,cells:[...]}] }
   주말 제외, 수업이 하나라도 있는 교시 범위만(빈 윗/아랫줄 잘라냄). */
export function weekGrid(timetable) {
  const rows = firstRows(timetable);
  if (!rows) return null;
  const cols = weekdayCols(rows[0]);
  const all = rows.slice(1).map((row) => {
    const p = parsePeriod(row[0]);
    return { no: p.no, time: p.time, cells: cols.map((c) => (row[c.idx] || "").trim()) };
  });
  // 수업 있는 첫~마지막 교시만 남김
  const has = (r) => r.cells.some((c) => c);
  let lo = all.findIndex(has);
  let hi = all.length - 1;
  while (hi >= 0 && !has(all[hi])) hi--;
  if (lo === -1) return { days: cols.map((c) => c.label), rows: [] };
  return { days: cols.map((c) => c.label), rows: all.slice(lo, hi + 1) };
}

/* 오늘 요일 수업: [{ no, time, name }] (주말이면 빈 배열) */
export function todayClasses(timetable) {
  const rows = firstRows(timetable);
  if (!rows) return [];
  const todayChar = DAY_CHARS[new Date().getDay()];
  if (!WEEKDAYS.includes(todayChar)) return [];
  const header = rows[0];
  let col = -1;
  for (let i = 1; i < header.length; i++) {
    if (String(header[i]).includes(todayChar)) { col = i; break; }
  }
  if (col === -1) return [];
  const out = [];
  for (const row of rows.slice(1)) {
    const name = (row[col] || "").trim();
    if (name) { const p = parsePeriod(row[0]); out.push({ no: p.no, time: p.time, name }); }
  }
  return out;
}
