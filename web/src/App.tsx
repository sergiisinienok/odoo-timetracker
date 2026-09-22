import { useCallback, useEffect, useState } from "react";

type Me = {
  employee_id: number;
  name: string;
  timezone: string;
};

type Assignment = {
  id: string;
  kind: string;
  project_id: number | null;
  so_line_id: number | null;
  label: string;
  is_default: boolean;
  start_date: string | null;
  end_date: string | null;
};

type Entry = {
  id: number | null;
  outbox_id: string | null;
  assignment_id: string;
  date: string;
  hours: number;
  note: string;
  project_id: number;
  so_line_id: number | null;
  sync_state: "synced" | "pending" | "failed";
};

function todayLocal(): string {
  const now = new Date();
  const offsetMs = now.getTimezoneOffset() * 60 * 1000;
  return new Date(now.getTime() - offsetMs).toISOString().slice(0, 10);
}

async function fetchJson<T>(url: string, init?: RequestInit): Promise<{ status: number; body: T }> {
  const res = await fetch(url, init);
  const body = (await res.json()) as T;
  return { status: res.status, body };
}

export function App() {
  const [me, setMe] = useState<Me | null | "loading">("loading");
  const [assignments, setAssignments] = useState<Assignment[]>([]);
  const [entries, setEntries] = useState<Entry[]>([]);
  const [assignmentId, setAssignmentId] = useState("");
  const [date, setDate] = useState(todayLocal());
  const [hours, setHours] = useState("1");
  const [note, setNote] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);

  const loadEntries = useCallback(async () => {
    // GET /api/entries returns the whole current month (step 2.4) — this
    // screen only shows today's, so filter client-side.
    const { body } = await fetchJson<Entry[]>("/api/entries");
    const today = todayLocal();
    setEntries(body.filter((entry) => entry.date === today));
  }, []);

  useEffect(() => {
    fetchJson<Me>("/api/me").then(({ status, body }) => {
      if (status !== 200) {
        setMe(null);
        return;
      }
      setMe(body);
    });
  }, []);

  useEffect(() => {
    if (me === "loading" || me === null) return;
    fetchJson<Assignment[]>("/api/assignments").then(({ body }) => {
      setAssignments(body);
      const preferred = body.find((a) => a.is_default) ?? body[0];
      if (preferred) setAssignmentId(preferred.id);
    });
    loadEntries();
  }, [me, loadEntries]);

  async function handleSave(e: React.FormEvent) {
    e.preventDefault();
    setError(null);
    setSaving(true);
    try {
      const { status, body } = await fetchJson<
        Entry | { detail: { error: string; message: string } }
      >("/api/entries", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ assignment_id: assignmentId, date, hours: Number(hours), note }),
      });
      // 201 synced, 202 pending — both are a successful save from the
      // employee's point of view (step 2.3's whole reason to exist).
      if (status !== 201 && status !== 202) {
        const detail = "detail" in body ? body.detail : { message: "Save failed" };
        setError(detail.message);
        return;
      }
      setNote("");
      await loadEntries();
    } finally {
      setSaving(false);
    }
  }

  if (me === "loading") return <p>Loading…</p>;

  if (me === null) {
    return (
      <main>
        <h1>Odoo Time Tracker</h1>
        <a href="/api/auth/google/login">Sign in with Google</a>
      </main>
    );
  }

  return (
    <main>
      <h1>Odoo Time Tracker</h1>
      <p>
        Signed in as {me.name} ({me.timezone})
      </p>

      <form onSubmit={handleSave}>
        <div>
          <label>
            Assignment{" "}
            <select value={assignmentId} onChange={(e) => setAssignmentId(e.target.value)}>
              {assignments.map((a) => (
                <option key={a.id} value={a.id}>
                  {a.label}
                  {a.is_default ? " (default)" : ""}
                </option>
              ))}
            </select>
          </label>
        </div>
        <div>
          <label>
            Date <input type="date" value={date} onChange={(e) => setDate(e.target.value)} />
          </label>
        </div>
        <div>
          <label>
            Hours{" "}
            <input
              type="number"
              step="0.25"
              min="0.25"
              value={hours}
              onChange={(e) => setHours(e.target.value)}
            />
          </label>
        </div>
        <div>
          <label>
            Note <input type="text" value={note} onChange={(e) => setNote(e.target.value)} />
          </label>
        </div>
        <button type="submit" disabled={saving || !assignmentId}>
          {saving ? "Saving…" : "Save"}
        </button>
      </form>

      {error && <p role="alert">{error}</p>}

      <h2>Today's entries</h2>
      {entries.length === 0 && <p>Nothing logged yet today.</p>}
      <ul>
        {entries.map((entry) => {
          const label = assignments.find((a) => a.id === entry.assignment_id)?.label ?? entry.assignment_id;
          return (
            <li key={entry.id ?? entry.outbox_id}>
              {entry.hours}h — {label}
              {entry.note.trim() ? ` — ${entry.note}` : ""}
              {entry.sync_state !== "synced" ? ` (${entry.sync_state})` : ""}
            </li>
          );
        })}
      </ul>
    </main>
  );
}
