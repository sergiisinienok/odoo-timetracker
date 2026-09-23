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
import { test, expect } from "@playwright/test";
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

async function restartApiToDropWarmCaches(): Promise<void> {
  // PeriodService caches validated-through for 5 minutes per employee
  // (step 2.2) — the running api process has no way to be told from
  // outside that a direct Odoo write just changed it. Restarting is the
  // only way to get a cold cache for this specific test without waiting
  // out the TTL.
  execFileSync("docker", ["compose", "restart", "api"], { cwd: REPO_ROOT });
  for (let i = 0; i < 30; i++) {
    try {
      const res = await fetch("http://localhost/api/healthz");
      if (res.ok) return;
    } catch {
      // not up yet
    }
    await new Promise((resolve) => setTimeout(resolve, 500));
  }
  throw new Error("api did not become healthy after restart");
}

test("logs an entry in under 60 seconds from a cold load", async ({ page, context }) => {
  const start = Date.now();

  await context.addCookies([
    { name: "tti_session", value: sessionCookie(TM_EMPLOYEE_ID), url: "http://localhost", httpOnly: true, sameSite: "Lax" },
  ]);
  await page.goto("/");

  await page.getByRole("spinbutton", { name: "Hours" }).fill("1");
  await page.getByRole("button", { name: "Save entry" }).click();
  await expect(page.getByText(/Entry saved|Waiting for Odoo/)).toBeVisible();

  const elapsedMs = Date.now() - start;
  expect(elapsedMs).toBeLessThan(60_000);

  // Clean up whatever the quick-add created (today, default assignment).
  const uid = await odooUid();
  const ids = (await odooCall("object", "execute_kw", [
    ODOO_DB,
    uid,
    ODOO_KEY,
    "account.analytic.line",
    "search",
    [[["employee_id", "=", TM_EMPLOYEE_ID], ["date", "=", todayIso()]]],
  ])) as number[];
  if (ids.length) {
    await odooCall("object", "execute_kw", [ODOO_DB, uid, ODOO_KEY, "account.analytic.line", "unlink", [ids]]);
  }
});

test("the daily cap is refused with a clear message", async ({ page, context }) => {
  const uid = await odooUid();
  // A pre-existing line consuming most of the day, over an unpaid
  // assignment (the internal project) so the app's own default-cap
  // config doesn't need touching for this test.
  const preExistingId = (await odooCall("object", "execute_kw", [
    ODOO_DB,
    uid,
    ODOO_KEY,
    "account.analytic.line",
    "create",
    [{ employee_id: TM_EMPLOYEE_ID, project_id: 1, date: todayIso(), unit_amount: 9.5, name: "cap test: pre-existing" }],
  ])) as number;

  try {
    await context.addCookies([
      { name: "tti_session", value: sessionCookie(TM_EMPLOYEE_ID), url: "http://localhost", httpOnly: true, sameSite: "Lax" },
    ]);
    await page.goto("/");

    await page.getByRole("spinbutton", { name: "Hours" }).fill("1");
    await page.getByRole("button", { name: "Save entry" }).click();

    await expect(page.getByText(/over your daily limit/)).toBeVisible();
  } finally {
    await odooCall("object", "execute_kw", [ODOO_DB, uid, ODOO_KEY, "account.analytic.line", "unlink", [[preExistingId]]]);
  }
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
    ["run", "python", "tools/outbox_test_seed.py", "insert", String(TM_EMPLOYEE_ID), todayIso(), "1.25", "pending render test"],
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

test("no API response body carries a rate, amount, or currency field", async ({ request }) => {
  const cookie = `tti_session=${sessionCookie(TM_EMPLOYEE_ID)}`;
  const forbidden = /\b(price|rate|currency)\b|"amount"|[$€£]/i;

  const endpoints = ["/api/me", "/api/assignments", "/api/periods", "/api/entries"];
  for (const url of endpoints) {
    const res = await request.get(`http://localhost${url}`, { headers: { Cookie: cookie } });
    const text = await res.text();
    expect(text, `${url} response body`).not.toMatch(forbidden);
  }

  // POST's response body too — the thing that most resembles an invoice line.
  const postRes = await request.post("http://localhost/api/entries", {
    headers: { Cookie: cookie, "Content-Type": "application/json" },
    data: { assignment_id: "internal", date: todayIso(), hours: 0.25, note: "money-leak check" },
  });
  const postText = await postRes.text();
  expect(postText).not.toMatch(forbidden);

  const created = JSON.parse(postText);
  if (created.id) {
    const uid = await odooUid();
    await odooCall("object", "execute_kw", [ODOO_DB, uid, ODOO_KEY, "account.analytic.line", "unlink", [[created.id]]]);
  }
});
