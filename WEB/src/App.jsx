import React, { useState, useEffect, useCallback } from "react";
import { Sidebar } from "./sidebar.jsx";
import { Login } from "./Login.jsx";
import { HomePage } from "./pages/Home.jsx";
import { NoticesPage } from "./pages/Notices.jsx";
import { LmsPage } from "./pages/Lms.jsx";
import { PortalPage } from "./pages/Portal.jsx";
import { ChatbotPage } from "./pages/Chatbot.jsx";
import { SettingsPage } from "./pages/Settings.jsx";
import { isAuthed, getProfile, auth } from "./api.js";

export default function App() {
  const [authed, setAuthed] = useState(isAuthed());
  const [page, setPage] = useState("home");
  const [user, setUser] = useState(null);

  const loadProfile = useCallback(() => {
    if (!isAuthed()) return;
    getProfile()
      .then(setUser)
      .catch(() => { auth.logout(); setAuthed(false); });
  }, []);

  useEffect(() => {
    if (authed) loadProfile();
  }, [authed, loadProfile]);

  if (!authed) {
    return <Login onAuthed={() => setAuthed(true)} />;
  }

  const PAGES = {
    home: <HomePage user={user} />,
    notices: <NoticesPage />,
    lms: <LmsPage user={user} />,
    portal: <PortalPage user={user} />,
    chatbot: <ChatbotPage user={user} />,
    settings: <SettingsPage user={user} onRefresh={loadProfile} />,
  };

  return (
    <div className="app-frame">
      <Sidebar page={page} onNav={setPage} />
      <main className="main" key={page}>
        {PAGES[page] || PAGES.home}
      </main>
    </div>
  );
}
