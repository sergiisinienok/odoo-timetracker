/**
 * Step 2.5's own test list: log an entry in under 60 seconds from a cold
 * load; the cap is refused with a clear message; a locked month renders
 * read-only with no editable control; the pending state renders during a
 * simulated outage; no API response body contains price/amount/rate/a
 * currency field.
 *
 * Same sign-in bypass as web/e2e/entry-flow.spec.ts, same reasoning —
 * see that file's own comment.
 */
import { E2E_PREFIX, createLine, createTask, expect, restartApiToDropWarmCaches, test } from "./fixtures";
import jwt from "jsonwebtoken";
import { execFileSync } from "node:child_process";
import path from "node:path";
import { fileURLToPath } from "node:url";

const __dirname = path.dirname(fileURLToPath(import.meta.url));

const SESSION_SECRET = process.env.SESSION_SECRET;
const ODOO_URL = process.env.ODOO_URL;
const ODOO_DB = process.env.ODOO_DB;
const ODOO_USER = process.env.ODOO_USER;
const ODOO_KEY = process.env.ODOO_KEY;

if (!SESSION_SECRET || !ODOO_URL || !ODOO_DB || !ODOO_USER || !ODOO_KEY) {
  throw new Error(
    "SESSION_SECRET/ODOO_URL/ODOO_DB/ODOO_USER/ODOO_KEY must be set — source ../.env before running `npm run test:e2e`",
  );
}

const TM_EMPLOYEE_ID = 1;
const PROJECT_ID = 2; // S00001, billable, employee 1 mapped
const API_DIR = path.resolve(__dirname, "../../api");
// .env's DATABASE_URL points at the "db" hostname, which only resolves
// inside the docker-compose network — same fix as api/tests/conftest.py's.
const SEED_SCRIPT_ENV = {
  ...process.env,
  DATABASE_URL: `postgresql+psycopg://tti:${process.env.POSTGRES_PASSWORD}@localhost:5432/tti`,
};

function sessionCookie(employeeId: number, timezone = "Europe/Lisbon") {
  return jwt.sign({ employee_id: employeeId, timezone }, SESSION_SECRET!, {
    algorithm: "HS256",
    expiresIn: "12h",
  });
}

async function odooCall(service: string, method: string, args: unknown[]): Promise<unknown> {
  const res = await fetch(`${ODOO_URL}/jsonrpc`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ jsonrpc: "2.0", method: "call", params: { service, method, args }, id: 1 }),
  });
  const body = await res.json();
  if (body.error) throw new Error(JSON.stringify(body.error));
  return body.result;
}

async function odooUid(): Promise<number> {
  return (await odooCall("common", "authenticate", [ODOO_DB, ODOO_USER, ODOO_KEY, {}])) as number;
}

// Deliberately NOT `.toISOString().slice(0, 10)` — that converts to UTC
// first, which silently shifts the date on any host running ahead of UTC
// (e.g. UTC+1 turns local midnight into the previous UTC day). Format from
// the local getters instead, same fix as web/src/api.ts's own todayLocal().
function isoDate(d: Date): string {
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
}

function todayIso(): string {
  return isoDate(new Date());
}

const REPO_ROOT = path.resolve(API_DIR, "..");

// The catalog is cached for 60 s, so a task created straight in Odoo only shows
// after the api restarts.
async function seedPrefilledTask(name: string, hours = 0.25): Promise<number> {
  const taskId = await createTask(PROJECT_ID, name);
  await createLine({ projectId: PROJECT_ID, taskId, date: todayIso(), hours, note: `${name} seed` });
  await restartApiToDropWarmCaches();
  return taskId;
}

test("logs an entry in under 60 seconds from a cold load", async ({ page, context }) => {
  await seedPrefilledTask("quick add task");
  const start = Date.now();

  await context.addCookies([
    { name: "tti_session", value: sessionCookie(TM_EMPLOYEE_ID), url: "http://localhost", httpOnly: true, sameSite: "Lax" },
  ]);
  await page.goto("/");

  await page.getByLabel("Project").selectOption(String(PROJECT_ID));
  await page.getByRole("spinbutton", { name: "Hours" }).fill("1");
  await page.getByPlaceholder("Note (optional)").fill(`${E2E_PREFIX} quick add`);
  await page.getByRole("button", { name: "Save entry" }).click();
  await expect(page.getByText(/Entry saved|Waiting for Odoo/)).toBeVisible();

  const elapsedMs = Date.now() - start;
  expect(elapsedMs).toBeLessThan(60_000);
  // No cleanup here: the fixtures remove every line and outbox row tagged E2E_PREFIX. (This used to delete every
  // line dated today for the employee, which would also have deleted real entries.)
});

test("the daily cap is refused with a clear message", async ({ page, context }) => {
  // A pre-existing line consuming most of the day. It sits on a task, so that
  // task is also the one the form pre-fills. The fixtures sweep it afterwards.
  await seedPrefilledTask("cap test task", 9.5);

  await context.addCookies([
    { name: "tti_session", value: sessionCookie(TM_EMPLOYEE_ID), url: "http://localhost", httpOnly: true, sameSite: "Lax" },
  ]);
  await page.goto("/");

  await page.getByLabel("Project").selectOption(String(PROJECT_ID));
  await page.getByRole("spinbutton", { name: "Hours" }).fill("1");
  await page.getByRole("button", { name: "Save entry" }).click();

  await expect(page.getByText(/over your daily limit/)).toBeVisible();
});

test("a locked month renders read-only with no editable control", async ({ page, context }) => {
  const uid = await odooUid();
  const [before] = (await odooCall("object", "execute_kw", [
    ODOO_DB,
    uid,
    ODOO_KEY,
    "hr.employee",
    "read",
    [[TM_EMPLOYEE_ID]],
    { fields: ["last_validated_timesheet_date"] },
  ])) as { last_validated_timesheet_date: string | false }[];
  const original = before.last_validated_timesheet_date || false;

  // Validate through the end of the current month — locks it entirely.
  const now = new Date();
  const lastOfMonth = isoDate(new Date(now.getFullYear(), now.getMonth() + 1, 0));
  await odooCall("object", "execute_kw", [
    ODOO_DB,
    uid,
    ODOO_KEY,
    "hr.employee",
    "write",
    [[TM_EMPLOYEE_ID], { last_validated_timesheet_date: lastOfMonth }],
  ]);
  await restartApiToDropWarmCaches();

  try {
    await context.addCookies([
      { name: "tti_session", value: sessionCookie(TM_EMPLOYEE_ID), url: "http://localhost", httpOnly: true, sameSite: "Lax" },
    ]);
    await page.goto("/");

    await expect(page.getByText(/is approved and closed/)).toBeVisible();
    await expect(page.getByRole("spinbutton", { name: "Hours" })).toHaveCount(0);
    await expect(page.getByRole("button", { name: "Save entry" })).toHaveCount(0);
  } finally {
    await odooCall("object", "execute_kw", [
      ODOO_DB,
      uid,
      ODOO_KEY,
      "hr.employee",
      "write",
      [[TM_EMPLOYEE_ID], { last_validated_timesheet_date: original }],
    ]);
    await restartApiToDropWarmCaches();
  }
});

test("the pending state renders during a simulated outage", async ({ page, context }) => {
  // See api/tools/outbox_test_seed.py's own docstring for why this seeds
  // a pending row directly rather than actually breaking Odoo
  // connectivity for the running api process.
  const outboxId = execFileSync(
    "uv",
    ["run", "python", "tools/outbox_test_seed.py", "insert", String(TM_EMPLOYEE_ID), todayIso(), "1.25", `${E2E_PREFIX} pending render test`],
    { cwd: API_DIR, encoding: "utf-8", env: SEED_SCRIPT_ENV },
  ).trim();

  try {
    await context.addCookies([
      { name: "tti_session", value: sessionCookie(TM_EMPLOYEE_ID), url: "http://localhost", httpOnly: true, sameSite: "Lax" },
    ]);
    await page.goto("/");

    await expect(page.locator(".pending-dot")).toBeVisible();
    await expect(page.locator(".bar-segment.pending")).toBeVisible();
  } finally {
    execFileSync("uv", ["run", "python", "tools/outbox_test_seed.py", "delete", outboxId], {
      cwd: API_DIR,
      env: SEED_SCRIPT_ENV,
    });
  }
});

test("no API response body carries a rate, amount, currency or billing field", async ({ request }) => {
  const cookie = `tti_session=${sessionCookie(TM_EMPLOYEE_ID)}`;
  // Field names only: task and project names are ops' data and may well say
  // "Flat Rate" or "Billable". The employee must never be shown billability.
  const forbiddenKey = /price|rate|amount|currency|bill|so_line|sale_line|invoice/i;

  function keysOf(value: unknown, into: Set<string> = new Set()): Set<string> {
    if (Array.isArray(value)) value.forEach((v) => keysOf(v, into));
    else if (value && typeof value === "object") {
      for (const [k, v] of Object.entries(value)) {
        into.add(k);
        keysOf(v, into);
      }
    }
    return into;
  }

  const endpoints = ["/api/me", "/api/catalog", "/api/periods", "/api/entries", "/api/entries/search"];
  for (const url of endpoints) {
    const res = await request.get(`http://localhost${url}`, { headers: { Cookie: cookie } });
    const keys = [...keysOf(await res.json())];
    expect(keys.filter((k) => forbiddenKey.test(k)), `${url} response keys`).toEqual([]);
  }

  // POST's response body too — the thing that most resembles an invoice line.
  const taskId = await createTask(PROJECT_ID, "money-leak task");
  await restartApiToDropWarmCaches();
  const postRes = await request.post("http://localhost/api/entries", {
    headers: { Cookie: cookie, "Content-Type": "application/json" },
    data: { project_id: PROJECT_ID, task_id: taskId, date: todayIso(), hours: 0.25, note: `${E2E_PREFIX} money-leak check` },
  });
  expect(postRes.status()).toBe(201);
  const keys = [...keysOf(await postRes.json())];
  expect(keys.filter((k) => forbiddenKey.test(k)), "POST /api/entries response keys").toEqual([]);
});
