import { useCallback, useEffect, useMemo, useState } from "react";
import type { CatalogProject, Entry, Me, Period } from "./api";
import { currentMonthKey, fetchJson, prefilledTask, todayLocal } from "./api";
import { EntryEditor } from "./EntryEditor";
import { describeSaveError } from "./errors";
import { Logo } from "./Logo";

const MONTH_NAMES = [
  "January",
  "February",
  "March",
  "April",
  "May",
  "June",
  "July",
  "August",
  "September",
  "October",
  "November",
  "December",
];
const DAY_NAMES = ["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"];

// Shown when the lists cannot be read (Odoo busy or unreachable). Nothing is lost: saved entries are in Odoo.
const LOAD_ERROR = "Couldn't load your projects just now — Odoo isn't answering. Reload in a moment; nothing you saved is lost.";

// Purely a visual reference for bar-width scaling, not a business rule —
// the server is the sole authority on the real cap (Appendix F: "the
// client mirrors the server's rules but the server is the authority").
const BAR_SCALE_HOURS = 10;

type DayGroup = {
  dateKey: string;
  dayOfMonth: number;
  weekday: string;
  isToday: boolean;
  entries: Entry[];
  totalHours: number;
  hasPending: boolean;
};

function buildDays(today: Date, entries: Entry[]): DayGroup[] {
  const byDate = new Map<string, Entry[]>();
  for (const entry of entries) {
    const list = byDate.get(entry.date) ?? [];
    list.push(entry);
    byDate.set(entry.date, list);
  }

  const days: DayGroup[] = [];
  const todayKey = todayLocal();
  for (let d = today.getDate(); d >= 1; d--) {
    const dateObj = new Date(today.getFullYear(), today.getMonth(), d);
    const dateKey = `${dateObj.getFullYear()}-${String(dateObj.getMonth() + 1).padStart(2, "0")}-${String(d).padStart(2, "0")}`;
    const dayEntries = byDate.get(dateKey) ?? [];
    days.push({
      dateKey,
      dayOfMonth: d,
      weekday: DAY_NAMES[dateObj.getDay()],
      isToday: dateKey === todayKey,
      entries: dayEntries,
      totalHours: dayEntries.reduce((sum, e) => sum + e.hours, 0),
      hasPending: dayEntries.some((e) => e.sync_state !== "synced"),
    });
  }
  return days;
}

export function MonthView({ me, onShowHistory }: { me: Me; onShowHistory: () => void }) {
  const [catalog, setCatalog] = useState<CatalogProject[]>([]);
  const [entries, setEntries] = useState<Entry[]>([]);
  const [periodState, setPeriodState] = useState<"open" | "locked" | null>(null);
  const [expandedDate, setExpandedDate] = useState<string | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);

  const [projectId, setProjectId] = useState<number | null>(null);
  const [taskId, setTaskId] = useState("");
  const [editingKey, setEditingKey] = useState<number | null>(null);
  const [date, setDate] = useState(todayLocal());
  const [hours, setHours] = useState("1");
  const [note, setNote] = useState("");
  const [saving, setSaving] = useState(false);
  const [message, setMessage] = useState<{ text: string; kind: "error" | "pending" | "ok" } | null>(null);

  const today = useMemo(() => new Date(), []);

  const load = useCallback(async () => {
    let catalogRes, entriesRes, periodsRes;
    try {
      [catalogRes, entriesRes, periodsRes] = await Promise.all([
        fetchJson<CatalogProject[]>("/api/catalog"),
        fetchJson<Entry[]>("/api/entries"),
        fetchJson<Period[]>("/api/periods"),
      ]);
    } catch {
      setLoadError(LOAD_ERROR);
      return;
    }
    if (catalogRes.status !== 200 || entriesRes.status !== 200 || periodsRes.status !== 200) {
      setLoadError(LOAD_ERROR);
      return;
    }
    setLoadError(null);
    setCatalog(catalogRes.body);
    setEntries(entriesRes.body);

    const key = currentMonthKey(new Date());
    const thisMonth = periodsRes.body.find((p) => p.month === key);
    setPeriodState(thisMonth?.state ?? "open");

    // First load: the employee's default project, with the task they last
    // used there. Later reloads keep whatever they have chosen.
    setProjectId((current) => {
      if (current !== null) return current;
      const preferred = catalogRes.body.find((p) => p.is_default) ?? catalogRes.body[0];
      setTaskId(prefilledTask(preferred));
      return preferred?.project_id ?? null;
    });
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  const days = useMemo(() => buildDays(today, entries), [today, entries]);
  const monthTotal = entries.reduce((sum, e) => sum + e.hours, 0);

  const projectTotals = useMemo(() => {
    const totals = new Map<number, { label: string; total: number }>();
    for (const entry of entries) {
      const row = totals.get(entry.project_id) ?? { label: entry.project_label, total: 0 };
      row.total += entry.hours;
      totals.set(entry.project_id, row);
    }
    return Array.from(totals.entries())
      .map(([id, row]) => ({ id, ...row }))
      .sort((a, b) => b.total - a.total);
  }, [entries]);

  const selectedProject = catalog.find((p) => p.project_id === projectId);

  function changeProject(id: number) {
    setProjectId(id);
    setTaskId(prefilledTask(catalog.find((p) => p.project_id === id)));
  }

  function adjustHours(delta: number) {
    const current = Number(hours) || 0;
    const next = Math.max(0.25, Math.round((current + delta) * 4) / 4);
    setHours(String(next));
  }

  async function handleSave(e: React.FormEvent) {
    e.preventDefault();
    setMessage(null);
    setSaving(true);
    try {
      const { status, body } = await fetchJson<Entry | { detail: { error: string; message: string } }>(
        "/api/entries",
        {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ project_id: projectId, task_id: Number(taskId), date, hours: Number(hours), note }),
        },
      );
      if (status !== 201 && status !== 202) {
        const detail = "detail" in body ? body.detail : { error: "unknown", message: "Save failed" };
        const weekday = DAY_NAMES[new Date(`${date}T00:00:00`).getDay()];
        setMessage({ text: describeSaveError(detail.error, detail.message, weekday), kind: "error" });
        return;
      }
      if (status === 202) {
        setMessage({ text: "Saved. Waiting for Odoo — nothing is lost.", kind: "pending" });
      } else {
        setMessage({ text: "Entry saved.", kind: "ok" });
      }
      setNote("");
      await load();
    } finally {
      setSaving(false);
    }
  }

  const monthLabel = MONTH_NAMES[today.getMonth()];
  const isLocked = periodState === "locked";

  return (
    <main className="app">
      <div className="history-header">
        <Logo />
        <p className="signed-in-as">
          {me.name} · {me.timezone}
        </p>
        <button type="button" className="back-link" onClick={onShowHistory}>
          Time tracking
        </button>
      </div>

      <div className="month-header">
        <h1>{monthLabel}</h1>
        <span className="month-total">{monthTotal.toFixed(1)} h</span>
      </div>

      {loadError && (
        <p className="save-message error" role="alert">
          {loadError}
        </p>
      )}

      {isLocked ? (
        <p className="period-banner locked">
          {monthLabel} is approved and closed. Ask your approver to change anything in it.
        </p>
      ) : (
        <form className="quick-add" onSubmit={handleSave}>
          <div className="quick-add-inner">
            <select
              aria-label="Project"
              value={projectId ?? ""}
              onChange={(e) => changeProject(Number(e.target.value))}
            >
              {catalog.map((p) => (
                <option key={p.project_id} value={p.project_id}>
                  {p.label}
                </option>
              ))}
            </select>
            <select aria-label="Task" value={taskId} onChange={(e) => setTaskId(e.target.value)}>
              <option value="" disabled>
                Choose a task
              </option>
              {(selectedProject?.tasks ?? []).map((t) => (
                <option key={t.id} value={t.id}>
                  {t.name}
                </option>
              ))}
            </select>
            {selectedProject && selectedProject.tasks.length === 0 && (
              <p className="no-tasks">This project has no open tasks yet. Ask ops to add one.</p>
            )}
            <input
              aria-label="Date"
              type="date"
              value={date}
              onChange={(e) => setDate(e.target.value)}
            />
            <div className="hours-stepper">
              <button type="button" onClick={() => adjustHours(-0.25)} aria-label="Decrease hours">
                −
              </button>
              <input
                aria-label="Hours"
                type="number"
                step="0.25"
                min="0.25"
                inputMode="decimal"
                value={hours}
                onChange={(e) => setHours(e.target.value)}
              />
              <button type="button" onClick={() => adjustHours(0.25)} aria-label="Increase hours">
                +
              </button>
            </div>
            <input
              aria-label="Note"
              type="text"
              placeholder="Note (optional)"
              value={note}
              onChange={(e) => setNote(e.target.value)}
            />
            <button type="submit" className="save-entry" disabled={saving || projectId === null || taskId === ""}>
              {saving ? "Saving…" : "Save entry"}
            </button>
            {message && (
              <p className={`save-message ${message.kind === "error" ? "error" : ""} ${message.kind === "pending" ? "pending" : ""}`} role={message.kind === "error" ? "alert" : "status"}>
                {message.text}
              </p>
            )}
          </div>
        </form>
      )}

      <details className="section" open>
        <summary>This month, by day</summary>
        {days.length === 0 || entries.length === 0 ? (
          <p className="empty-month">Nothing logged yet. Start with today.</p>
        ) : (
          <ul className="day-list">
            {days.map((day) => {
              const expanded = expandedDate === day.dateKey;
              const hasEntries = day.entries.length > 0;
              return (
                <li key={day.dateKey}>
                  <div className={`day-row${hasEntries ? "" : " is-empty"}`}>
                    <span className={`day-label${day.isToday ? " is-today" : ""}`}>
                      {day.weekday} {day.dayOfMonth}
                    </span>
                    <div className="day-bar">
                      {day.entries.map((entry, i) => (
                        <span
                          key={entry.id ?? entry.outbox_id ?? i}
                          className={`bar-segment${entry.sync_state !== "synced" ? " pending" : ""}`}
                          style={{ width: `${Math.max(4, (entry.hours / BAR_SCALE_HOURS) * 100)}%` }}
                        />
                      ))}
                    </div>
                    <span className="day-hours">
                      {day.totalHours > 0 ? day.totalHours.toFixed(1) : ""}
                      {day.hasPending && <span className="pending-dot">·</span>}
                    </span>
                    {hasEntries ? (
                      <button
                        type="button"
                        className="day-expand"
                        aria-label={expanded ? "Collapse day" : "Expand day"}
                        onClick={() => setExpandedDate(expanded ? null : day.dateKey)}
                      >
                        ▸
                      </button>
                    ) : (
                      <span className="day-expand-spacer" />
                    )}
                  </div>
                  {expanded && (
                    <ul className="day-entries">
                      {day.entries.map((entry, i) => {
                        const key = entry.id ?? entry.outbox_id ?? i;
                        const editing = entry.id !== null && editingKey === entry.id;
                        return (
                          <li key={key}>
                            {editing ? (
                              <EntryEditor
                                entry={entry}
                                catalog={catalog}
                                onCancel={() => setEditingKey(null)}
                                onSaved={async () => {
                                  setEditingKey(null);
                                  await load();
                                }}
                              />
                            ) : (
                              <>
                                {entry.hours.toFixed(2)}h — {entry.project_label} — {entry.task_name ?? "No task"}
                                {entry.note.trim() ? ` — ${entry.note}` : ""}
                                {entry.sync_state !== "synced" ? ` (${entry.sync_state})` : ""}
                                {!isLocked && entry.id !== null && entry.sync_state === "synced" && (
                                  <button type="button" className="entry-edit" onClick={() => setEditingKey(entry.id)}>
                                    Edit
                                  </button>
                                )}
                              </>
                            )}
                          </li>
                        );
                      })}
                    </ul>
                  )}
                </li>
              );
            })}
          </ul>
        )}
      </details>

      {projectTotals.length > 0 && (
        <details className="section" open>
          <summary>This month, by project</summary>
          <ul className="project-totals">
            {projectTotals.map((p) => (
              <li key={p.id}>
                <span>{p.label}</span>
                <span className="hours">{p.total.toFixed(1)}</span>
              </li>
            ))}
          </ul>
        </details>
      )}
    </main>
  );
}
