/* KNU PICK — API 레이어.
   실 백엔드(FastAPI) 호출 + JWT 토큰 관리. 일부 화면(홈 추천/마감 집계,
   포털 졸업표 변환 미구현분)은 목업을 유지하고 주석으로 표시한다. */

const TOKEN_KEY = "knu_pick_token";

export function getToken() {
  return localStorage.getItem(TOKEN_KEY);
}
export function setToken(t) {
  if (t) localStorage.setItem(TOKEN_KEY, t);
  else localStorage.removeItem(TOKEN_KEY);
}
export function isAuthed() {
  return !!getToken();
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

// ── 공지 ──────────────────────────────────────────────
const CATEGORY_LABEL = {
  scholarship: "Scholarship",
  academic: "Academic",
  career: "Employment",
  event: "Event",
  etc: "General",
};
export async function getNotices() {
  const r = await req("GET", "/api/notices?limit=30");
  return (r.notices || []).map((n) => ({
    urgent: false,
    source: n.source_name || "공지",
    dept: "",
    deadlineLabel: n.end_date ? `~ ${n.end_date}` : "",
    deadlineWarm: false,
    reg: n.posted_at ? `Reg: ${n.posted_at}` : "",
    title: n.title,
    body: n.summary || n.content || "",
    target: (n.target && n.target[0]) || "전체",
    tags: (n.keywords || []).slice(0, 3).map((k) => `# ${k}`),
    attachments: [],
    category: CATEGORY_LABEL[n.category] || "General",
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
export const NOTICE_CATEGORIES = ["All", "Academic", "Employment", "Event", "General"];
export const INTEREST_KEYWORD_POOL = [
  "인턴", "장학금", "캡스톤", "해커톤", "교환학생",
  "공모전", "근로장학", "특강", "동아리", "취업박람회",
];
export const MAX_INTERESTS = 6;

// 홈 추천공지·마감은 집계 API 미구현 — 목업 유지(TODO: 백엔드 집계 엔드포인트)
export const MOCK = {
  recommended: [
    { d: "D-5", warm: false, title: "Global Exchange Scholarship Program", body: "가을학기 교환학생 프로그램 신청이 시작되었습니다.", tags: ["#Scholarship", "#Global"] },
    { d: "D-2", warm: true, active: true, title: "AI Research Lab Assistant Recruitment", body: "NLP·컴퓨터비전 팀 학부 연구원을 모집합니다.", tags: ["#Research", "#AI"] },
    { d: "D-12", warm: false, title: "Spring Festival Volunteer Registration", body: "봄 축제 운영 자원봉사자를 모집합니다.", tags: ["#Volunteer", "#CampusLife"] },
  ],
  deadlines: [
    { d: "D-1", warm: true, title: "자료구조 과제 #3", sub: "LMS 제출", cat: "전공" },
    { d: "D-2", warm: false, title: "수강 정정 마감", sub: "포털", cat: "학사" },
    { d: "D-5", warm: false, title: "교환학생 장학금", sub: "포털 신청", cat: "장학" },
  ],
};

export const chatSuggestions = [
  { icon: "coins", label: "장학금 정보 알려줘" },
  { icon: "book", label: "수강신청 방법" },
  { icon: "utensils", label: "학식 메뉴" },
];
