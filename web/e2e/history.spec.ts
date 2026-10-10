/**
 * Step 2.6's own test list: an employee with entries in three months,
 * one of them locked — filters return the right sets, search matches
 * note text, the locked month exposes no edit affordance and its API
 * mutations return 409.
 *
 * Same sign-in bypass as web/e2e/entry-flow.spec.ts, same reasoning —
 * see that file's own comment.
 */
import { E2E_PREFIX, expect, test } from "./fixtures";
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
const REPO_ROOT = path.resolve(__dirname, "../..");

function sessionCookie(employeeId: number, timezone = "Europe/Lisbon") {
  return jwt.sign({ employee_id: employeeId, timezone }, SESSION_SECRET!, {
    algorithm: "HS256",
    expiresIn: "12h",
  });
}

async function odooCall(service: string, method: string, args: unknown[]): Promise<any> {
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
  return await odooCall("common", "authenticate", [ODOO_DB, ODOO_USER, ODOO_KEY, {}]);
}

// See month-view.spec.ts's own comment on why not `.toISOString()`.
function isoDate(d: Date): string {
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
}

function monthsAgo(n: number): Date {
  const now = new Date();
  return new Date(now.getFullYear(), now.getMonth() - n, 5);
}

function monthKey(d: Date): string {
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}`;
}

async function restartApiToDropWarmCaches(): Promise<void> {
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

test("three months, one locked: filters, search, and locked-month read-only enforcement", async ({
  page,
  context,
  request,
}) => {
  const uid = await odooUid();
  const marker = Math.random().toString(36).slice(2, 10);

  const monthA = monthsAgo(2); // will be locked
  const monthB = monthsAgo(1);
  const monthC = monthsAgo(0);

  async function createLine(date: Date, note: string): Promise<number> {
    return await odooCall("object", "execute_kw", [
      ODOO_DB,
      uid,
      ODOO_KEY,
      "account.analytic.line",
      "create",
      [{ employee_id: TM_EMPLOYEE_ID, project_id: 1, date: isoDate(date), unit_amount: 1.0, name: `${E2E_PREFIX} ${marker} ${note}` }],
    ]);
  }

  const lineA = await createLine(monthA, "alpha");
  const lineB = await createLine(monthB, "bravo");
  const lineC = await createLine(monthC, "charlie unique note");

  const [before] = (await odooCall("object", "execute_kw", [
    ODOO_DB,
    uid,
    ODOO_KEY,
    "hr.employee",
    "read",
    [[TM_EMPLOYEE_ID]],
    { fields: ["last_validated_timesheet_date"] },
  ])) as { last_validated_timesheet_date: string | false }[];
  const originalValidatedThrough = before.last_validated_timesheet_date || false;

  const lastOfMonthA = new Date(monthA.getFullYear(), monthA.getMonth() + 1, 0);
  await odooCall("object", "execute_kw", [
    ODOO_DB,
    uid,
    ODOO_KEY,
    "hr.employee",
    "write",
    [[TM_EMPLOYEE_ID], { last_validated_timesheet_date: isoDate(lastOfMonthA) }],
  ]);
  await restartApiToDropWarmCaches();

  try {
    await context.addCookies([
      { name: "tti_session", value: sessionCookie(TM_EMPLOYEE_ID), url: "http://localhost", httpOnly: true, sameSite: "Lax" },
    ]);
    await page.goto("/");
    await page.getByRole("button", { name: "Time tracking" }).click();

    // Month filter: only month A's entry, and it's marked locked.
    await page.getByLabel("Month").fill(monthKey(monthA));
    await expect(page.getByText(`${marker} alpha`)).toBeVisible();
    await expect(page.getByText(`${marker} bravo`)).not.toBeVisible();
    await expect(page.locator(".history-locked-badge")).toBeVisible();

    // Switch to month C: open, no locked badge, different entry.
    await page.getByLabel("Month").fill(monthKey(monthC));
    await expect(page.getByText(`${marker} charlie unique note`)).toBeVisible();
    await expect(page.getByText(`${marker} alpha`)).not.toBeVisible();
    await expect(page.locator(".history-locked-badge")).toHaveCount(0);

    // Clear the month filter, search by note text instead.
    await page.getByLabel("Month").fill("");
    await page.getByLabel("Search notes").fill(`${marker} charlie`);
    await expect(page.getByText(`${marker} charlie unique note`)).toBeVisible();
    await expect(page.getByText(`${marker} alpha`)).not.toBeVisible();
    await expect(page.getByText(`${marker} bravo`)).not.toBeVisible();

    // The locked month's entries expose no edit affordance anywhere in
    // this read-only listing (step 2.6 doesn't add editing here at all —
    // editing an open day remains the month view's job).
    await page.getByLabel("Search notes").fill("");
    await page.getByLabel("Month").fill(monthKey(monthA));
    await expect(page.getByRole("button", { name: /edit/i })).toHaveCount(0);
    await expect(page.getByRole("button", { name: /delete/i })).toHaveCount(0);

    // And the API itself refuses a mutation against that locked date,
    // independent of what the UI does or doesn't render.
    const cookie = `tti_session=${sessionCookie(TM_EMPLOYEE_ID)}`;
    const patchRes = await request.patch(`http://localhost/api/entries/${lineA}`, {
      headers: { Cookie: cookie, "Content-Type": "application/json" },
      data: { project_id: 1, task_id: 1, date: isoDate(monthA), hours: 2.0, note: "should be refused" },
    });
    expect(patchRes.status()).toBe(409);
  } finally {
    await odooCall("object", "execute_kw", [ODOO_DB, uid, ODOO_KEY, "account.analytic.line", "unlink", [[lineA, lineB, lineC]]]);
    await odooCall("object", "execute_kw", [
      ODOO_DB,
      uid,
      ODOO_KEY,
      "hr.employee",
      "write",
      [[TM_EMPLOYEE_ID], { last_validated_timesheet_date: originalValidatedThrough }],
    ]);
    await restartApiToDropWarmCaches();
  }
});
