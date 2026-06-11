import React, { createContext, useContext, useState, useCallback, useEffect } from "react";
import * as api from "./api.js";

/* 앱 전역 상태. 프로필·데이터 캐시·액션을 한 곳에 둬서
   페이지를 이동해도 상태가 유지된다(페이지별 로컬 state 금지). */
const Ctx = createContext(null);
export const useApp = () => useContext(Ctx);

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
  const [chatMsgs, setChatMsgs] = useState([]);

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

  const loadTimetable = useCallback(async (force) => {
    if (timetable && !force) return timetable;
    const t = await api.getMeTimetable();
    setTimetable(t);
    return t;
  }, [timetable]);

  const saveInterests = useCallback(async (interests) => {
    const p = await api.saveInterests(interests);
    setProfile(p);
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
    saveInterests, syncPortal, syncLms,
    setLmsTasks,
    chatMsgs, setChatMsgs,
  };
  return <Ctx.Provider value={value}>{children}</Ctx.Provider>;
}
