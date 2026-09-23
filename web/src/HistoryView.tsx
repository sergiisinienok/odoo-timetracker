import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import type { Assignment, Entry, Period } from "./api";
import { fetchJson } from "./api";

const MONTH_SHORT = [
  "Jan",
  "Feb",
  "Mar",
  "Apr",
  "May",
  "Jun",
  "Jul",
  "Aug",
  "Sep",
  "Oct",
  "Nov",
  "Dec",
];

const PAGE_SIZE = 50;

function formatDate(iso: string): string {
  const [year, month, day] = iso.split("-").map(Number);
  return `${MONTH_SHORT[month - 1]} ${day}, ${year}`;
}

function buildQuery(params: Record<string, string>): string {
  const search = new URLSearchParams();
  for (const [key, value] of Object.entries(params)) {
    if (value) search.set(key, value);
  }
  const qs = search.toString();
  return qs ? `?${qs}` : "";
}

export function HistoryView({ onBack }: { onBack: () => void }) {
  const [assignments, setAssignments] = useState<Assignment[]>([]);
  const [periods, setPeriods] = useState<Period[]>([]);

  const [month, setMonth] = useState("");
  const [assignmentId, setAssignmentId] = useState("");
  const [qInput, setQInput] = useState("");
  const [q, setQ] = useState("");

  const [items, setItems] = useState<Entry[]>([]);
  const [total, setTotal] = useState(0);
  const [loading, setLoading] = useState(false);

  const requestId = useRef(0);

  useEffect(() => {
    fetchJson<Assignment[]>("/api/assignments").then(({ body }) => setAssignments(body));
    fetchJson<Period[]>("/api/periods").then(({ body }) => setPeriods(body));
  }, []);

  // Debounce the free-text search so a fast typist doesn't fire a
  // request per keystroke — the other filters (month, assignment) are
  // discrete choices and apply immediately.
  useEffect(() => {
    const timer = setTimeout(() => setQ(qInput), 300);
    return () => clearTimeout(timer);
  }, [qInput]);

  const load = useCallback(async (offset: number, append: boolean) => {
    const myRequest = ++requestId.current;
    setLoading(true);
    try {
      const query = buildQuery({
        month,
        assignment_id: assignmentId,
        q,
        limit: String(PAGE_SIZE),
        offset: String(offset),
      });
      const { body } = await fetchJson<{ items: Entry[]; total: number }>(`/api/entries/search${query}`);
      if (myRequest !== requestId.current) return; // a newer filter change superseded this
      setTotal(body.total);
      setItems((current) => (append ? [...current, ...body.items] : body.items));
    } finally {
      if (myRequest === requestId.current) setLoading(false);
    }
  }, [month, assignmentId, q]);

  useEffect(() => {
    load(0, false);
  }, [load]);

  const lockedMonths = useMemo(() => new Set(periods.filter((p) => p.state === "locked").map((p) => p.month)), [periods]);
  const assignmentLabel = useMemo(() => {
    const byId = new Map(assignments.map((a) => [a.id, a.label]));
    return (id: string) => byId.get(id) ?? id;
  }, [assignments]);

  const canLoadMore = items.length < total;

  return (
    <main className="app">
      <div className="history-header">
        <h1>Time tracking</h1>
        <button type="button" className="back-link" onClick={onBack}>
          Back to month
        </button>
      </div>

      <div className="history-filters">
        <input aria-label="Month" type="month" value={month} onChange={(e) => setMonth(e.target.value)} />
        <select aria-label="Assignment filter" value={assignmentId} onChange={(e) => setAssignmentId(e.target.value)}>
          <option value="">All assignments</option>
          {assignments.map((a) => (
            <option key={a.id} value={a.id}>
              {a.label}
            </option>
          ))}
        </select>
        <input
          aria-label="Search notes"
          type="text"
          placeholder="Search notes"
          value={qInput}
          onChange={(e) => setQInput(e.target.value)}
        />
      </div>

      <p className="history-count">
        {total} {total === 1 ? "entry" : "entries"}
      </p>

      {items.length === 0 && !loading ? (
        <p className="empty-month">Nothing matches. Try different filters.</p>
      ) : (
        <ul className="history-list">
          {items.map((entry) => {
            const entryMonth = entry.date.slice(0, 7);
            const locked = lockedMonths.has(entryMonth);
            return (
              <li key={entry.id ?? entry.outbox_id} className="history-row">
                <span className="history-date">{formatDate(entry.date)}</span>
                <span className="history-assignment">{assignmentLabel(entry.assignment_id)}</span>
                <span className="history-hours">{entry.hours.toFixed(2)}</span>
                <span className="history-note">{entry.note.trim()}</span>
                {locked && <span className="history-locked-badge">locked</span>}
              </li>
            );
          })}
        </ul>
      )}

      {canLoadMore && (
        <button type="button" className="load-more" disabled={loading} onClick={() => load(items.length, true)}>
          {loading ? "Loading…" : "Load more"}
        </button>
      )}
    </main>
  );
}
