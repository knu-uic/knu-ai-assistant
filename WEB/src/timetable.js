/* 포털 시간표 데이터 변환.
   원본 shape: [{ rows: [["교시","월요일",...], [period, monCell, ...], ...] }]
   rows[0] = 헤더, 각 셀은 과목 문자열(빈 칸 가능). */

const DAY_CHARS = ["일", "월", "화", "수", "목", "금", "토"];

function firstTable(timetable) {
  if (!Array.isArray(timetable) || timetable.length === 0) return null;
  const rows = timetable[0]?.rows;
  if (!Array.isArray(rows) || rows.length < 2) return null;
  return rows;
}

/* 전체 주간 격자: { header, rows } — header[0]="교시" 제외한 요일들 */
export function weekGrid(timetable) {
  const rows = firstTable(timetable);
  if (!rows) return null;
  return { header: rows[0], body: rows.slice(1) };
}

/* 오늘 요일의 수업만: [{ period, name }] */
export function todayClasses(timetable) {
  const rows = firstTable(timetable);
  if (!rows) return [];
  const header = rows[0];
  const todayChar = DAY_CHARS[new Date().getDay()];
  // 헤더에서 오늘 요일 컬럼 인덱스 찾기 (예: "월요일"에 "월" 포함)
  let col = -1;
  for (let i = 1; i < header.length; i++) {
    if (String(header[i]).includes(todayChar)) { col = i; break; }
  }
  if (col === -1) return [];
  const out = [];
  for (const row of rows.slice(1)) {
    const cell = (row[col] || "").trim();
    if (cell) out.push({ period: row[0], name: cell });
  }
  return out;
}
