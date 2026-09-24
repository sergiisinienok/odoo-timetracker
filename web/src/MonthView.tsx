import { useCallback, useEffect, useMemo, useState } from "react";
import type { Assignment, Entry, Me, Period } from "./api";
import { currentMonthKey, fetchJson, todayLocal } from "./api";
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

// Purely a visual reference for bar-width scaling, not a business rule —
// the server is the sole authority on the real cap (Appendix F: "the
// client mirrors the server's rules but the server is the authority").
const BAR_SCALE_HOURS = 10;

// Appendix F's Voice section gives exact copy for the known rejections —
// the raw {error, message} from the API is a technical detail, not what
// an employee should read. Unknown codes fall back to the server's own
// message rather than inventing copy for a case the plan didn't specify.
function describeSaveError(code: string, rawMessage: string, weekday: string): string {
  switch (code) {
    case "daily_cap_exceeded":
      // The plan's own example names a specific number ("over 10 hours"),
      // but the real cap isn't exposed to the client (server is the sole
      // authority on it) — phrased generically rather than guessing it.
      return `That would put ${weekday} over your daily limit. Reduce the entry, or ask ops to raise your daily limit.`;
    case "period_locked":
      return "That date is approved and closed. Ask your approver to change anything in it.";
    case "assignment_not_valid_on_date":
      return "That assignment isn't valid on this date.";
    case "invalid_increment":
      return "Hours must be a positive multiple of a quarter hour.";
    default:
      return rawMessage;
  }
}

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
  const [assignments, setAssignments] = useState<Assignment[]>([]);
  const [entries, setEntries] = useState<Entry[]>([]);
  const [periodState, setPeriodState] = useState<"open" | "locked" | null>(null);
  const [expandedDate, setExpandedDate] = useState<string | null>(null);

  const [assignmentId, setAssignmentId] = useState("");
  const [date, setDate] = useState(todayLocal());
  const [hours, setHours] = useState("1");
  const [note, setNote] = useState("");
  const [saving, setSaving] = useState(false);
  const [message, setMessage] = useState<{ text: string; kind: "error" | "pending" | "ok" } | null>(null);

  const today = useMemo(() => new Date(), []);

  const load = useCallback(async () => {
    const [assignmentsRes, entriesRes, periodsRes] = await Promise.all([
      fetchJson<Assignment[]>("/api/assignments"),
      fetchJson<Entry[]>("/api/entries"),
      fetchJson<Period[]>("/api/periods"),
    ]);
    setAssignments(assignmentsRes.body);
    setEntries(entriesRes.body);

    const key = currentMonthKey(new Date());
    const thisMonth = periodsRes.body.find((p) => p.month === key);
    setPeriodState(thisMonth?.state ?? "open");

    setAssignmentId((current) => {
      if (current) return current;
      const preferred = assignmentsRes.body.find((a) => a.is_default) ?? assignmentsRes.body[0];
      return preferred?.id ?? "";
    });
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  const days = useMemo(() => buildDays(today, entries), [today, entries]);
  const monthTotal = entries.reduce((sum, e) => sum + e.hours, 0);

  const assignmentTotals = useMemo(() => {
    const totals = new Map<string, number>();
    for (const entry of entries) {
      totals.set(entry.assignment_id, (totals.get(entry.assignment_id) ?? 0) + entry.hours);
    }
    return Array.from(totals.entries())
      .map(([id, total]) => ({
        id,
        label: assignments.find((a) => a.id === id)?.label ?? id,
        total,
      }))
      .sort((a, b) => b.total - a.total);
  }, [entries, assignments]);

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
          body: JSON.stringify({ assignment_id: assignmentId, date, hours: Number(hours), note }),
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

      {isLocked ? (
        <p className="period-banner locked">
          {monthLabel} is approved and closed. Ask your approver to change anything in it.
        </p>
      ) : (
        <form className="quick-add" onSubmit={handleSave}>
          <div className="quick-add-inner">
            <select
              aria-label="Assignment"
              value={assignmentId}
              onChange={(e) => setAssignmentId(e.target.value)}
            >
              {assignments.map((a) => (
                <option key={a.id} value={a.id}>
                  {a.label}
                </option>
              ))}
            </select>
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
            <button type="submit" className="save-entry" disabled={saving || !assignmentId}>
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
                        const label = assignments.find((a) => a.id === entry.assignment_id)?.label ?? entry.assignment_id;
                        return (
                          <li key={entry.id ?? entry.outbox_id ?? i}>
                            {entry.hours.toFixed(2)}h — {label}
                            {entry.note.trim() ? ` — ${entry.note}` : ""}
                            {entry.sync_state !== "synced" ? ` (${entry.sync_state})` : ""}
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

      {assignmentTotals.length > 0 && (
        <details className="section" open>
          <summary>This month, by assignment</summary>
          <ul className="assignment-totals">
            {assignmentTotals.map((a) => (
              <li key={a.id}>
                <span>{a.label}</span>
                <span className="hours">{a.total.toFixed(1)}</span>
              </li>
            ))}
          </ul>
        </details>
      )}
    </main>
  );
}
