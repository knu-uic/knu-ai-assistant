import React, { useState } from "react";
import { Sidebar } from "./sidebar.jsx";
import { Login } from "./Login.jsx";
import { HomePage } from "./pages/Home.jsx";
import { NoticesPage } from "./pages/Notices.jsx";
import { LmsPage } from "./pages/Lms.jsx";
import { PortalPage } from "./pages/Portal.jsx";
import { ChatbotPage } from "./pages/Chatbot.jsx";
import { SettingsPage } from "./pages/Settings.jsx";
import { useApp } from "./store.jsx";

export default function App() {
  const { authed, onAuthed } = useApp();
  const [page, setPage] = useState("home");

  if (!authed) {
    return <Login onAuthed={onAuthed} />;
  }

  const PAGES = {
    home: HomePage,
    notices: NoticesPage,
    lms: LmsPage,
    portal: PortalPage,
    chatbot: ChatbotPage,
    settings: SettingsPage,
  };
  const Current = PAGES[page] || HomePage;

  return (
    <div className="app-frame">
      <Sidebar page={page} onNav={setPage} />
      <main className="main">
        <Current />
      </main>
    </div>
  );
}
