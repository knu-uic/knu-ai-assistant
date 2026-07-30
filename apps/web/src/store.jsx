import React, { createContext, useContext, useState, useCallback, useEffect } from "react";
import * as api from "./api.js";

/* 앱 전역 상태. 프로필·데이터 캐시·액션을 한 곳에 둬서
   페이지를 이동해도 상태가 유지된다(페이지별 로컬 state 금지). */
const Ctx = createContext(null);
export const useApp = () => useContext(Ctx);

const chatKey = (u) => `knu_chat_${u}`;
const newId = () => Date.now().toString(36) + Math.random().toString(36).slice(2, 6);
// 첫 사용자 질문 앞 20자로 대화 제목 자동 생성.
function deriveTitle(messages) {
  const first = messages.find((m) => m.role === "user");
  const t = (first?.content || "새 대화").trim();
  return t.length > 20 ? t.slice(0, 20) + "…" : t;
}

export function AppProvider({ children }) {
  const [authed, setAuthed] = useState(api.isAuthed());
  const [profile, setProfile] = useState(null);
  const [profileLoading, setProfileLoading] = useState(false);

  // 데이터 캐시 — 한번 불러오면 페이지 이동해도 유지
  const [notices, setNotices] = useState(null);
  const [lmsTasks, setLmsTasks] = useState(null);
  const [lmsCourses, setLmsCourses] = useState(null);
  const [portalData, setPortalData] = useState(null);
  const [timetable, setTimetable] = useState(null);
  const [home, setHome] = useState(null);

  // 대화 기록 — username별 localStorage에 영속화. currentId는 항상 유효한 id를
  // 가리키되, 해당 대화는 첫 메시지가 생기기 전엔 conversations에 안 들어간다
  // (= 빈 새 대화는 목록에 안 보임).
  const [conversations, setConversations] = useState([]);
  const [currentId, setCurrentId] = useState(newId);

  // 로그인/계정 전환 시 그 username 키에서 로드. 로그아웃이면 비움.
  useEffect(() => {
    const u = api.currentUsername();
    if (!authed || !u) {
      setConversations([]);
      setCurrentId(newId());
      return;
    }
    const raw = api.getStoredItem(chatKey(u));
    let convs = [];
    try {
      convs = raw ? JSON.parse(raw) : [];
    } catch {
      // 손상된 로컬 대화 기록은 무시하고 새 기록으로 시작한다.
    }
    setConversations(convs);
    setCurrentId(convs[0]?.id ?? newId());
  }, [authed]);

  // conversations 변경 시 현재 username 키로 flush. 로그아웃 상태(!authed)에선
  // 쓰지 않아 기존 기록을 빈 배열로 덮어쓰지 않는다(로그아웃해도 기록 유지).
  useEffect(() => {
    const u = api.currentUsername();
    if (!authed || !u) return;
    api.setStoredItem(chatKey(u), JSON.stringify(conversations));
  }, [conversations, authed]);

  const chatMsgs = conversations.find((c) => c.id === currentId)?.messages ?? [];

  // 기존 Chatbot.jsx 인터페이스 유지: setChatMsgs(updater). 현재 대화가 아직
  // 목록에 없으면 첫 메시지에서 새 대화로 생성한다.
  const setChatMsgs = useCallback((updater) => {
    setConversations((convs) => {
      const idx = convs.findIndex((c) => c.id === currentId);
      const prev = idx >= 0 ? convs[idx].messages : [];
      const next = typeof updater === "function" ? updater(prev) : updater;
      const now = Date.now();
      if (idx < 0) {
        return [{ id: currentId, title: deriveTitle(next), messages: next, createdAt: now, updatedAt: now }, ...convs];
      }
      const out = [...convs];
      out[idx] = { ...out[idx], messages: next, updatedAt: now, title: out[idx].title || deriveTitle(next) };
      return out;
    });
  }, [currentId]);

  const newConversation = useCallback(() => setCurrentId(newId()), []);
  const loadConversation = useCallback((id) => setCurrentId(id), []);
  const deleteConversation = useCallback((id) => {
    setConversations((convs) => convs.filter((c) => c.id !== id));
    setCurrentId((cur) => (cur === id ? newId() : cur));
  }, []);

  const refreshProfile = useCallback(async () => {
    if (!api.isAuthed()) return;
    setProfileLoading(true);
    try {
      const p = await api.getProfile();
      setProfile(p);
    } catch {
      api.auth.logout();
      setAuthed(false);
      setProfile(null);
    } finally {
      setProfileLoading(false);
    }
  }, []);

  useEffect(() => {
    if (authed) refreshProfile();
  }, [authed, refreshProfile]);

  const onAuthed = useCallback(() => setAuthed(true), []);
  const logout = useCallback(() => {
    api.auth.logout();
    setAuthed(false);
    setProfile(null);
    setNotices(null);
    setLmsTasks(null);
    setLmsCourses(null);
    setPortalData(null);
    setTimetable(null);
    setHome(null);
  }, []);

  // lazy 로더 — 캐시 있으면 그대로, 없으면 fetch
  const loadNotices = useCallback(async (force) => {
    if (notices && !force) return notices;
    const n = await api.getNotices();
    setNotices(n);
    return n;
  }, [notices]);

  const loadLms = useCallback(async (force) => {
    if (lmsTasks && lmsCourses && !force) return;
    const [t, c] = await Promise.all([api.getLmsTasks(), api.getLmsCourses()]);
    setLmsTasks(t);
    setLmsCourses(c);
  }, [lmsTasks, lmsCourses]);

  const loadPortal = useCallback(async (force) => {
    if (portalData && !force) return portalData;
    const d = await api.getPortalData();
    setPortalData(d);
    return d;
  }, [portalData]);

  const loadHome = useCallback(async (force) => {
    if (home && !force) return home;
    const h = await api.getHome();
    setHome(h);
    return h;
  }, [home]);

  const loadTimetable = useCallback(async (force) => {
    if (timetable && !force) return timetable;
    const t = await api.getMeTimetable();
    setTimetable(t);
    return t;
  }, [timetable]);

  const saveInterests = useCallback(async (interests) => {
    const p = await api.saveInterests(interests);
    setProfile(p);
    setHome(null);  // 관심사 바뀌면 추천 순서 달라짐 → 다음 진입 시 재조회
  }, []);

  const saveFavorites = useCallback(async (favs) => {
    const p = await api.saveFavorites(favs);
    setProfile(p);
  }, []);

  const toggleTaskDone = useCallback(async (id, done) => {
    await api.setTaskDone(id, done);
    setLmsTasks((ts) => (ts || []).map((t) => (t.id === id ? { ...t, done } : t)));
  }, []);

  const removeTask = useCallback(async (id) => {
    await api.deleteTask(id);
    setLmsTasks((ts) => (ts || []).filter((t) => t.id !== id));
  }, []);

  // 동기화 성공 후 관련 캐시 무효화 + 프로필 갱신
  const syncPortal = useCallback(async (sid, pw, onStep) => {
    const r = await api.syncPortal(sid, pw, onStep);
    await refreshProfile();
    setPortalData(null);
    setTimetable(null);
    return r;
  }, [refreshProfile]);

  const syncLms = useCallback(async (sid, pw, onStep) => {
    const r = await api.syncLms(sid, pw, onStep);
    setLmsTasks(null);
    setLmsCourses(null);
    await refreshProfile();
    return r;
  }, [refreshProfile]);

  const value = {
    authed, onAuthed, logout,
    profile, profileLoading, refreshProfile,
    notices, loadNotices,
    lmsTasks, lmsCourses, loadLms,
    portalData, loadPortal,
    timetable, loadTimetable,
    home, loadHome,
    saveInterests, saveFavorites, toggleTaskDone, removeTask,
    syncPortal, syncLms,
    setLmsTasks,
    chatMsgs, setChatMsgs,
    conversations, currentId, newConversation, loadConversation, deleteConversation,
  };
  return <Ctx.Provider value={value}>{children}</Ctx.Provider>;
}
