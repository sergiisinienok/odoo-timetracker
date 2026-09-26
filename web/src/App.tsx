import { useEffect, useState } from "react";
import type { Me } from "./api";
import { fetchJson } from "./api";
import { HistoryView } from "./HistoryView";
import { Logo } from "./Logo";
import { MonthView } from "./MonthView";
import "./styles.css";

const AUTH_ERRORS: Record<string, { title: string; body: string }> = {
  employee_not_found: {
    title: "No employee found for your account",
    body:
      "You signed in successfully, but Odoo has no active employee whose work email matches your Google account. " +
      "Ask an Odoo administrator to create an employee for you (or set your work email on your existing employee), then sign in again.",
  },
  employee_ambiguous: {
    title: "More than one employee matches your account",
    body:
      "Odoo has several active employees with your work email, so the app can't tell which one is you. " +
      "Ask an Odoo administrator to fix the duplicate, then sign in again.",
  },
  foreign_domain: {
    title: "Wrong Google account",
    body: "Sign in with your company Google account (@particlesglobal.com).",
  },
  email_unverified: {
    title: "Email not verified",
    body: "Google reports that this email address is not verified. Use a different account.",
  },
};

function authErrorFromUrl() {
  const code = new URLSearchParams(window.location.search).get("auth_error");
  if (!code) return null;
  return (
    AUTH_ERRORS[code] ?? {
      title: "Sign-in failed",
      body: "Something went wrong while signing you in. Try again, or contact an administrator if it keeps happening.",
    }
  );
}

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
    const authError = authErrorFromUrl();
    return (
      <main className="app signin">
        <Logo />
        <h1>Time Tracker</h1>
        {authError && (
          <div className="auth-error" role="alert">
            <h2>{authError.title}</h2>
            <p>{authError.body}</p>
          </div>
        )}
        <a className="signin-link" href="/api/auth/google/login">
          {authError ? "Sign in with a different account" : "Sign in with Google"}
        </a>
      </main>
    );
  }

  if (view === "history") {
    return <HistoryView onBack={() => setView("month")} />;
  }

  return <MonthView me={me} onShowHistory={() => setView("history")} />;
}
