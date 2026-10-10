import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import type { CatalogProject, Entry, Period } from "./api";
import { fetchJson } from "./api";
import { Logo } from "./Logo";

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
  const [catalog, setCatalog] = useState<CatalogProject[]>([]);
  const [periods, setPeriods] = useState<Period[]>([]);

  const [month, setMonth] = useState("");
  const [projectId, setProjectId] = useState("");
  const [taskId, setTaskId] = useState("");
  const [qInput, setQInput] = useState("");
  const [q, setQ] = useState("");

  const [items, setItems] = useState<Entry[]>([]);
  const [total, setTotal] = useState(0);
  const [loading, setLoading] = useState(false);
  const [loadError, setLoadError] = useState<string | null>(null);

  const requestId = useRef(0);

  useEffect(() => {
    fetchJson<CatalogProject[]>("/api/catalog")
      .then(({ status, body }) => status === 200 && setCatalog(body))
      .catch(() => undefined); // the filters just stay empty; the list itself reports its own failure
    fetchJson<Period[]>("/api/periods")
      .then(({ status, body }) => status === 200 && setPeriods(body))
      .catch(() => undefined);
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
        project_id: projectId,
        task_id: taskId,
        q,
        limit: String(PAGE_SIZE),
        offset: String(offset),
      });
      const { status, body } = await fetchJson<{ items: Entry[]; total: number }>(`/api/entries/search${query}`);
      if (myRequest !== requestId.current) return; // a newer filter change superseded this
      if (status !== 200) {
        setLoadError("Couldn't load your history just now — Odoo isn't answering. Try again in a moment.");
        return;
      }
      setLoadError(null);
      setTotal(body.total);
      setItems((current) => (append ? [...current, ...body.items] : body.items));
    } catch {
      if (myRequest === requestId.current) {
        setLoadError("Couldn't load your history just now — Odoo isn't answering. Try again in a moment.");
      }
    } finally {
      if (myRequest === requestId.current) setLoading(false);
    }
  }, [month, projectId, taskId, q]);

  useEffect(() => {
    load(0, false);
  }, [load]);

  const lockedMonths = useMemo(() => new Set(periods.filter((p) => p.state === "locked").map((p) => p.month)), [periods]);
  const tasksOfProject = useMemo(
    () => catalog.find((p) => String(p.project_id) === projectId)?.tasks ?? [],
    [catalog, projectId],
  );

  const canLoadMore = items.length < total;

  return (
    <main className="app">
      <div className="history-header">
        <Logo />
        <h1>Time tracking</h1>
        <button type="button" className="back-link" onClick={onBack}>
          <svg className="back-arrow" viewBox="0 0 24 24" width="16" height="16" aria-hidden="true" focusable="false">
            <path d="M20 12H4M4 12L10.5 5.5M4 12L10.5 18.5" fill="none" stroke="currentColor" strokeWidth="1.5" />
          </svg>
          Back to month
        </button>
      </div>

      <div className="history-filters">
        <input aria-label="Month" type="month" value={month} onChange={(e) => setMonth(e.target.value)} />
        <select
          aria-label="Project filter"
          value={projectId}
          onChange={(e) => {
            setProjectId(e.target.value);
            setTaskId("");
          }}
        >
          <option value="">All projects</option>
          {catalog.map((p) => (
            <option key={p.project_id} value={p.project_id}>
              {p.label}
            </option>
          ))}
        </select>
        {projectId !== "" && (
          <select aria-label="Task filter" value={taskId} onChange={(e) => setTaskId(e.target.value)}>
            <option value="">All tasks</option>
            {tasksOfProject.map((t) => (
              <option key={t.id} value={t.id}>
                {t.name}
              </option>
            ))}
          </select>
        )}
        <input
          aria-label="Search notes"
          type="text"
          placeholder="Search notes"
          value={qInput}
          onChange={(e) => setQInput(e.target.value)}
        />
      </div>

      {loadError && (
        <p className="save-message error" role="alert">
          {loadError}
        </p>
      )}

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
                <span className="history-project">
                  {entry.project_label} — {entry.task_name ?? "No task"}
                </span>
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
