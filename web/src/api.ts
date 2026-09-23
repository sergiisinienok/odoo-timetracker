export type Me = {
  employee_id: number;
  name: string;
  timezone: string;
};

export type Assignment = {
  id: string;
  kind: string;
  project_id: number | null;
  so_line_id: number | null;
  label: string;
  is_default: boolean;
  start_date: string | null;
  end_date: string | null;
};

export type Entry = {
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

export type Period = {
  month: string; // "YYYY-MM"
  state: "open" | "locked";
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
