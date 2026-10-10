export type Me = {
  employee_id: number;
  name: string;
  timezone: string;
};

export type CatalogTask = { id: number; name: string };

// One entry per project this employee may log against, with its open tasks.
// Deliberately no billing field of any kind: the employee is never shown it.
export type CatalogProject = {
  project_id: number;
  label: string;
  is_default: boolean;
  last_used_task_id: number | null;
  tasks: CatalogTask[];
};

export type Entry = {
  id: number | null;
  outbox_id: string | null;
  project_id: number;
  project_label: string;
  task_id: number | null; // null on lines logged before tasks existed
  task_name: string | null;
  date: string;
  hours: number;
  note: string;
  sync_state: "synced" | "pending" | "failed";
};

export type Period = {
  month: string; // "YYYY-MM"
  state: "open" | "locked";
};

export type EntrySearchResult = {
  items: Entry[];
  total: number;
};

export type ErrorBody = { detail: { error: string; message: string } };

export async function fetchJson<T>(url: string, init?: RequestInit): Promise<{ status: number; body: T }> {
  const res = await fetch(url, init);
  const body = (await res.json()) as T;
  return { status: res.status, body };
}

export function currentMonthKey(now: Date): string {
  return `${now.getFullYear()}-${String(now.getMonth() + 1).padStart(2, "0")}`;
}

export function todayLocal(): string {
  const now = new Date();
  const offsetMs = now.getTimezoneOffset() * 60 * 1000;
  return new Date(now.getTime() - offsetMs).toISOString().slice(0, 10);
}

/** The task to pre-fill for a project: the one last used there, if it is still open. */
export function prefilledTask(project: CatalogProject | undefined): string {
  if (!project || project.last_used_task_id === null) return "";
  return project.tasks.some((t) => t.id === project.last_used_task_id) ? String(project.last_used_task_id) : "";
}
