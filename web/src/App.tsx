import { useEffect, useState } from "react";
import type { Me } from "./api";
import { fetchJson } from "./api";
import { HistoryView } from "./HistoryView";
import { MonthView } from "./MonthView";
import "./styles.css";

export function App() {
  const [me, setMe] = useState<Me | null | "loading">("loading");
  const [view, setView] = useState<"month" | "history">("month");

  useEffect(() => {
    fetchJson<Me>("/api/me").then(({ status, body }) => {
      setMe(status === 200 ? body : null);
    });
  }, []);

  if (me === "loading") return <p>Loading…</p>;

  if (me === null) {
    return (
      <main className="app signin">
        <h1>Odoo Time Tracker</h1>
        <a className="signin-link" href="/api/auth/google/login">
          Sign in with Google
        </a>
      </main>
    );
  }

  if (view === "history") {
    return <HistoryView onBack={() => setView("month")} />;
  }

  return <MonthView me={me} onShowHistory={() => setView("history")} />;
}
