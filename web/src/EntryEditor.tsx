import { useState } from "react";
import type { CatalogProject, Entry } from "./api";
import { fetchJson, prefilledTask } from "./api";
import { describeSaveError } from "./errors";

const DAY_NAMES = ["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"];

/**
 * Edits one saved line in place. A line logged before tasks existed opens with
 * the task picker empty and required: it cannot be saved until one is chosen.
 */
export function EntryEditor({
  entry,
  catalog,
  onSaved,
  onCancel,
}: {
  entry: Entry;
  catalog: CatalogProject[];
  onSaved: () => void;
  onCancel: () => void;
}) {
  const [projectId, setProjectId] = useState(entry.project_id);
  const [taskId, setTaskId] = useState(entry.task_id === null ? "" : String(entry.task_id));
  const [hours, setHours] = useState(String(entry.hours));
  const [note, setNote] = useState(entry.note);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // The line's own project and task stay selectable even if they have since left
  // the catalog (task closed, project unlisted): keeping them is always allowed.
  const projects: { id: number; label: string }[] = catalog.map((p) => ({ id: p.project_id, label: p.label }));
  if (!projects.some((p) => p.id === entry.project_id)) {
    projects.unshift({ id: entry.project_id, label: entry.project_label });
  }
  const current = catalog.find((p) => p.project_id === projectId);
  const tasks = (current?.tasks ?? []).map((t) => ({ id: t.id, name: t.name }));
  if (projectId === entry.project_id && entry.task_id !== null && !tasks.some((t) => t.id === entry.task_id)) {
    tasks.unshift({ id: entry.task_id, name: `${entry.task_name ?? "Task"} (closed)` });
  }

  function changeProject(id: number) {
    setProjectId(id);
    if (id === entry.project_id) {
      setTaskId(entry.task_id === null ? "" : String(entry.task_id));
    } else {
      setTaskId(prefilledTask(catalog.find((p) => p.project_id === id)));
    }
  }

  async function save(e: React.FormEvent) {
    e.preventDefault();
    setError(null);
    setSaving(true);
    try {
      const { status, body } = await fetchJson<Entry | { detail: { error: string; message: string } }>(
        `/api/entries/${entry.id}`,
        {
          method: "PATCH",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            project_id: projectId,
            task_id: taskId === "" ? null : Number(taskId),
            date: entry.date,
            hours: Number(hours),
            note,
          }),
        },
      );
      if (status !== 200 && status !== 202) {
        const detail = "detail" in body ? body.detail : { error: "unknown", message: "Save failed" };
        const weekday = DAY_NAMES[new Date(`${entry.date}T00:00:00`).getDay()];
        setError(describeSaveError(detail.error, detail.message, weekday));
        return;
      }
      onSaved();
    } finally {
      setSaving(false);
    }
  }

  return (
    <form className="entry-editor" onSubmit={save}>
      <select aria-label="Edit project" value={projectId} onChange={(e) => changeProject(Number(e.target.value))}>
        {projects.map((p) => (
          <option key={p.id} value={p.id}>
            {p.label}
          </option>
        ))}
      </select>
      <select aria-label="Edit task" value={taskId} onChange={(e) => setTaskId(e.target.value)} required>
        <option value="" disabled>
          Choose a task
        </option>
        {tasks.map((t) => (
          <option key={t.id} value={t.id}>
            {t.name}
          </option>
        ))}
      </select>
      <input
        aria-label="Edit hours"
        type="number"
        step="0.25"
        min="0.25"
        inputMode="decimal"
        value={hours}
        onChange={(e) => setHours(e.target.value)}
      />
      <input aria-label="Edit note" type="text" value={note} onChange={(e) => setNote(e.target.value)} />
      <div className="entry-editor-actions">
        <button type="submit" className="save-entry" disabled={saving || taskId === ""}>
          {saving ? "Saving…" : "Save changes"}
        </button>
        <button type="button" className="back-link" onClick={onCancel}>
          Cancel
        </button>
      </div>
      {error && (
        <p className="save-message error" role="alert">
          {error}
        </p>
      )}
    </form>
  );
}
