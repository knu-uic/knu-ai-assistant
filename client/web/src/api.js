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
function expireSession(token) {
  // A late response from an old session must not log out a newly signed-in user.
  if (getToken() !== token) return;
  setToken(null);
  if (typeof window !== 'undefined') window.dispatchEvent(new Event('knu-auth-expired'));
}
// JWT payload의 sub(=portal:학번)을 클라이언트에서 디코드. 대화 기록 localStorage
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
    expireSession(token);
    throw new Error("세션이 만료되었습니다. 다시 로그인해주세요.");
  }
  const data = await res.json().catch(() => ({}));
  if (!res.ok) {
    const error = new Error(typeof data.detail === 'string' ? data.detail : `요청 실패 (${res.status})`);
    error.status = res.status;
    throw error;
  }
  return data;
}

// ── 인증 ──────────────────────────────────────────────
export const auth = {
  async portalLogin(studentId, password) {
    const r = await req("POST", "/api/auth/portal-login", {
      student_id: studentId,
      password,
    });
    setToken(r.access_token);
    return r;
  },
  async logout() {
    const token = getToken();
    try {
      if (token) await fetch("/api/auth/logout", {
        method: "POST", headers: { Authorization: `Bearer ${token}` },
      });
    } catch {
      // 네트워크가 끊겨도 브라우저의 인증 정보는 즉시 제거한다.
    } finally {
      setToken(null);
    }
  },
};

export const llmAccounts = {
  list: () => req("GET", "/api/me/llm/accounts"),
  addOpenAIKey: (api_key) => req("POST", "/api/me/llm/openai-key", { api_key }),
  addGeminiKey: (api_key) => req("POST", "/api/me/llm/google-key", { api_key }),
  startCodexLogin: () => req("POST", "/api/me/llm/codex/login"),
  pollCodexLogin: (id) => req("GET", `/api/me/llm/codex/login/${encodeURIComponent(id)}`),
  models: (id) => req("GET", `/api/me/llm/accounts/${encodeURIComponent(id)}/models`),
  select: (id, model) => req("PUT", `/api/me/llm/accounts/${encodeURIComponent(id)}/selection`, { model }),
  remove: (id) => req("DELETE", `/api/me/llm/accounts/${encodeURIComponent(id)}`),
};

export const chatModels = () => req("GET", "/api/chat/models");
export const conversationApi = {
  list: cursor => req('GET', '/api/me/conversations' + (cursor ? `?cursor=${encodeURIComponent(cursor)}` : '')),
  get: id => req('GET', `/api/me/conversations/${encodeURIComponent(id)}`),
  remove: (id, revision) => req('DELETE', `/api/me/conversations/${encodeURIComponent(id)}?revision=${revision}`),
  import: items => req('POST', '/api/me/conversations/import', {items}),
};

// ── 챗봇 ──────────────────────────────────────────────
// 비스트리밍 호출도 스트리밍과 동일하게 대화 기록을 전달한다.
export async function askChatbot(question, history = [], source = "personal") {
  const r = await req("POST", "/api/chat", { question, history, source });
  return {
    intro: r.answer || "",
    bullets: [],
    outro: "",
    citations: [],
  };
}

// 스트리밍 챗봇. SSE를 fetch+ReadableStream으로 수동 파싱(EventSource는
// Authorization 헤더를 못 실어서 토큰 인증과 함께 쓸 수 없음).
// 콜백: onStep(상태문구) / onToken(누적텍스트) / 반환값=최종 {grounded}
export async function streamChatbot(question, history = [], { onStep, onToken, source = "personal", conversationId, revision=0, requestId } = {}) {
  const token = getToken();
  const res = await fetch("/api/chat/stream", {
    method: "POST",
    headers: { Authorization: `Bearer ${token}`, "Content-Type": "application/json" },
    body: JSON.stringify(conversationId ? {question,source,conversation_id:conversationId,revision,request_id:requestId} : { question, history, source }),
  });
  if (res.status === 401) {
    expireSession(token);
    throw new Error("세션이 만료되었습니다. 다시 로그인해주세요.");
  }
  if (!res.ok || !res.body) {
    const error = await res.json().catch(() => ({}));
    throw new Error(error.detail || `요청 실패 (${res.status})`);
  }

  const reader = res.body.getReader();
  const decoder = new TextDecoder();
  let buf = "";
  let text = "";
  let final = null, finished = false;

  // "event: X\ndata: {...}\n\n" 블록 단위 파싱
  const handle = (block) => {
    const ev = /event:\s*(.+)/.exec(block)?.[1]?.trim();
    const dataLine = /data:\s*([\s\S]*)/.exec(block)?.[1]?.trim();
    if (!ev || dataLine == null) return;
    let data = {};
    try { data = JSON.parse(dataLine); } catch { return; }
    if (ev === "step") { onStep?.(data.label || "답변을 준비하고 있어요..."); }
    else if (ev === "token") { text += data.text || ""; onToken?.(text); }
    else if (ev === "answer") { final=data; if(!text) { text = data.answer || ""; onToken?.(text); } }
    else if (ev === "done") finished=true;
    else if (ev === "error") { const error=new Error(data.detail || "답변 생성에 실패했습니다."); error.status=data.status; throw error; }
  };

  try {
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
    buf += decoder.decode();
    if(buf.trim()) handle(buf);
    if(!finished || !final) throw new Error('답변 연결이 중단됐습니다. 대화 목록에서 저장 여부를 확인해주세요.');
    return { ...final, intro: text, outro: "" };
  } finally {
    await reader.cancel().catch(() => {});
    reader.releaseLock();
  }
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
    tags: [],
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
