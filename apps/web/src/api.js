/* KNU PICK — API 레이어.
   실 백엔드(FastAPI) 호출 + JWT 토큰 관리. 일부 화면(홈 추천/마감 집계,
   포털 졸업표 변환 미구현분)은 목업을 유지하고 주석으로 표시한다. */

const TOKEN_KEY = "knu_pick_token";
const memoryStorage = new Map();

// WKWebView나 보안이 강화된 임베드 브라우저에서는 localStorage가 없거나
// 접근 자체가 예외를 던질 수 있다. 이 경우 현재 웹 세션 동안만 유지되는
// 메모리 저장소를 사용해 앱의 첫 렌더가 중단되지 않도록 한다.
export function getStoredItem(key) {
  try {
    if (typeof localStorage !== "undefined") return localStorage.getItem(key);
  } catch {
    // Fall through to the in-memory store.
  }
  return memoryStorage.get(key) ?? null;
}

export function setStoredItem(key, value) {
  try {
    if (typeof localStorage !== "undefined") {
      if (value == null) localStorage.removeItem(key);
      else localStorage.setItem(key, value);
      return;
    }
  } catch {
    // Fall through to the in-memory store.
  }
  if (value == null) memoryStorage.delete(key);
  else memoryStorage.set(key, value);
}

export function getToken() {
  return getStoredItem(TOKEN_KEY);
}
export function setToken(t) {
  setStoredItem(TOKEN_KEY, t || null);
}
export function isAuthed() {
  return !!getToken();
}
// JWT payload의 sub(=username)을 클라이언트에서 디코드. 대화 기록 localStorage
// 키를 사용자별로 분리하는 데만 쓴다(인증 판단 아님). 토큰 없거나 깨지면 null.
export function currentUsername() {
  const t = getToken();
  if (!t) return null;
  try {
    const p = JSON.parse(atob(t.split(".")[1].replace(/-/g, "+").replace(/_/g, "/")));
    return p.sub || null;
  } catch {
    return null;
  }
}

async function req(method, path, body) {
  const headers = { "Content-Type": "application/json" };
  const token = getToken();
  if (token) headers.Authorization = `Bearer ${token}`;
  const res = await fetch(path, {
    method,
    headers,
    body: body ? JSON.stringify(body) : undefined,
  });
  if (res.status === 401) {
    setToken(null);
    throw new Error("세션이 만료되었습니다. 다시 로그인해주세요.");
  }
  const data = await res.json().catch(() => ({}));
  if (!res.ok) throw new Error(data.detail || `요청 실패 (${res.status})`);
  return data;
}

// ── 인증 ──────────────────────────────────────────────
export const auth = {
  async signupRequest(email) {
    return req("POST", "/api/auth/signup/request", { email });
  },
  async signupVerify(email, code, username, password) {
    const r = await req("POST", "/api/auth/signup/verify", {
      email,
      code,
      username,
      password,
    });
    setToken(r.access_token);
    return r;
  },
  async login(username, password) {
    const r = await req("POST", "/api/auth/login", { username, password });
    setToken(r.access_token);
    return r;
  },
  logout() {
    setToken(null);
  },
};

// ── 챗봇 ──────────────────────────────────────────────
// 백엔드는 flat 키(answer 문자열)를 반환 → AnswerCard 구조로 어댑트.
export async function askChatbot(question, major) {
  const r = await req("POST", "/api/chat", { question, major });
  return {
    intro: r.answer || "",
    bullets: [],
    outro: r.grounded === false ? "근거 문서를 찾지 못했습니다." : "",
    citations: [],
  };
}

// 노드 "완료" → 다음 단계 진행 문구. step은 노드가 끝날 때 오므로
// 방금 끝난 노드가 아니라 "이제 할 일"을 보여줘야 자연스럽다.
const STEP_LABEL = {
  router: "관련 공지를 찾고 있어요...",   // 분석 끝 → 검색 시작
  retriever: "답변을 생성하고 있어요...",
  broad_retriever: "답변을 생성하고 있어요...",
  verifier: "답변을 검토하고 있어요...",
};

// 스트리밍 챗봇. SSE를 fetch+ReadableStream으로 수동 파싱(EventSource는
// Authorization 헤더를 못 실어서 토큰 인증과 함께 쓸 수 없음).
// 콜백: onStep(상태문구) / onToken(누적텍스트) / 반환값=최종 {grounded}
export async function streamChatbot(question, major, { onStep, onToken } = {}) {
  const params = new URLSearchParams({ question });
  if (major) params.set("major", major);
  const res = await fetch(`/api/chat/stream?${params}`, {
    headers: { Authorization: `Bearer ${getToken()}` },
  });
  if (res.status === 401) {
    setToken(null);
    throw new Error("세션이 만료되었습니다. 다시 로그인해주세요.");
  }
  if (!res.ok || !res.body) throw new Error(`요청 실패 (${res.status})`);

  const reader = res.body.getReader();
  const decoder = new TextDecoder();
  let buf = "";
  let text = "";
  let meta = {};

  // "event: X\ndata: {...}\n\n" 블록 단위 파싱
  const handle = (block) => {
    const ev = /event:\s*(.+)/.exec(block)?.[1]?.trim();
    const dataLine = /data:\s*([\s\S]*)/.exec(block)?.[1]?.trim();
    if (!ev || dataLine == null) return;
    let data = {};
    try { data = JSON.parse(dataLine); } catch { return; }
    if (ev === "step") { if (STEP_LABEL[data.node]) onStep?.(STEP_LABEL[data.node]); }
    else if (ev === "token") { text += data.text || ""; onToken?.(text); }
    else if (ev === "answer") meta = data;
    else if (ev === "error") throw new Error(data.detail || "답변 생성에 실패했습니다.");
  };

  for (;;) {
    const { done, value } = await reader.read();
    if (done) break;
    buf += decoder.decode(value, { stream: true });
    let i;
    while ((i = buf.indexOf("\n\n")) !== -1) {
      handle(buf.slice(0, i));
      buf = buf.slice(i + 2);
    }
  }
  return {
    intro: text,
    outro: meta.grounded === false ? "근거 문서를 찾지 못했습니다." : "",
  };
}

// ── 공지 ──────────────────────────────────────────────
// 백엔드 category는 한글 그대로("장학"/"수강"/"취업(진로)"/"행사(공모전)"/"일반(기타)").
export async function getNotices() {
  const r = await req("GET", "/api/notices?limit=100");
  return (r.notices || []).map((n) => ({
    urgent: false,
    source: n.source_name || "공지",
    dept: n.department || "",
    deadlineLabel: n.deadline_label || "",
    deadlineWarm: n.deadline_tone === "danger" || n.deadline_tone === "warning",
    reg: n.posted_at ? `Reg: ${n.posted_at}` : "",
    title: n.title,
    body: n.summary || n.content || "",
    target: (n.target && n.target[0]) || "전체",
    tags: (n.keywords || []).slice(0, 3).map((k) => `# ${k}`),
    attachments: [],
    category: n.category || "일반(기타)",
    url: n.url,
  }));
}

// ── 본인 데이터 (/api/me/*) ────────────────────────────
export async function getProfile() {
  return req("GET", "/api/me");
}
export async function getMeTimetable() {
  const r = await req("GET", "/api/me/timetable");
  return r.timetable || [];
}
export async function getPortalData() {
  return req("GET", "/api/me/portal");
}
export async function getLmsTasks() {
  const r = await req("GET", "/api/me/lms/tasks");
  // 백엔드 task → 디자인 TaskRow shape (type/due/done/course/progress)
  return (r.tasks || []).map((t) => ({
    id: t.id,
    type: t.task_type,
    title: t.title,
    course: t.course_name || "기타",
    due_date: t.due_date || null,   // ISO 문자열 또는 null — D-day는 화면에서 계산
    url: t.url || null,
    progress: t.progress,
    done: t.is_done,
  }));
}
export async function saveInterests(interests) {
  return req("POST", "/api/me/interests", { interests });
}
export async function saveFavorites(favorite_courses) {
  return req("POST", "/api/me/lms/favorites", { favorite_courses });
}
export async function setTaskDone(taskId, isDone) {
  await req("POST", `/api/me/lms/tasks/${taskId}/done`, { is_done: isDone });
}
export async function deleteTask(taskId) {
  await req("DELETE", `/api/me/lms/tasks/${taskId}`);
}
export async function getHome() {
  const r = await req("GET", "/api/me/home");
  return {
    recommended: (r.recommended || []).map((n) => ({
      title: n.title,
      body: n.summary || "",
      url: n.url,
      d: n.d_label,
      warm: n.days_left != null && n.days_left <= 3,
      tags: [
        ...(n.category ? [`# ${n.category}`] : []),
        ...(n.matched_keywords || []).map((k) => `# ${k}`),
      ],
    })),
    deadlines: (r.deadlines || []).map((d) => ({
      title: d.title,
      url: d.url,
      sub: d.end_date ? `마감 ${d.end_date}` : "",
      cat: d.category || "",
      d: d.d_label,
      warm: d.days_left != null && d.days_left <= 3,
    })),
  };
}

export async function getLmsCourses() {
  const r = await req("GET", "/api/me/lms/courses");
  return (r.courses || []).map((c) => ({
    course_id: c.course_id,
    course_name: c.course_name,
    fav: false,
  }));
}

// ── 동기화 트리거 (잡 + 폴링) ──────────────────────────
async function pollJob(base, jobId, onStep) {
  const deadline = Date.now() + 240000;
  while (Date.now() < deadline) {
    const s = await req("GET", `${base}/${jobId}`);
    if (s.status === "done") return s.result;
    if (s.status === "failed") {
      if (s.needs_reconnect) {
        const e = new Error(s.detail || "재연결이 필요합니다.");
        e.needsReconnect = true;
        throw e;
      }
      throw new Error(s.detail || "동기화에 실패했습니다.");
    }
    if (s.step) onStep?.(s.step);
    await new Promise((r) => setTimeout(r, 2000));
  }
  throw new Error("동기화 시간이 초과되었습니다.");
}

export async function syncPortal(studentId, password, onStep) {
  const r = await req("POST", "/api/portal/sync/start", {
    student_id: studentId,
    password,
  });
  return pollJob("/api/portal/sync", r.job_id, onStep);
}
export async function syncLms(studentId, password, onStep) {
  const r = await req("POST", "/api/lms/sync/start", {
    student_id: studentId,
    password: password || undefined,
  });
  return pollJob("/api/lms/sync", r.job_id, onStep);
}

// ── 정적/상수 + 목업(엔드포인트 없음 — 다음 작업) ──────
export const NOTICE_CATEGORIES = ["전체", "장학", "수강", "취업(진로)", "행사(공모전)", "일반(기타)"];
export const INTEREST_KEYWORD_POOL = [
  "인턴", "장학금", "캡스톤", "해커톤", "교환학생",
  "공모전", "근로장학", "특강", "동아리", "취업박람회",
];
export const MAX_INTERESTS = 6;

export const chatSuggestions = [
  { icon: "coins", label: "장학금 정보 알려줘" },
  { icon: "book", label: "수강신청 방법" },
  { icon: "calendar", label: "학사일정 알려줘" },
  { icon: "landmark", label: "도서관 운영시간" },
];
