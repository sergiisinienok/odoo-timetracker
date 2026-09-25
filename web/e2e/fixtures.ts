/**
 * Shared Playwright fixtures for the e2e suite. Every spec imports `test` and
 * `expect` from here instead of from @playwright/test.
 *
 * Why this exists: the suite shares one live Odoo employee (id 1) and one
 * Postgres outbox, and it used to trust each test to tidy up after itself.
 * Two things went wrong in practice:
 *
 *  1. A stale lock perpetuated itself. The lock tests read the employee's
 *     validated-through date, set their own, and "restore" what they read. If
 *     September was already locked (for any reason) they put the lock back, and
 *     every test needing an open month timed out after 30 s with no hint why.
 *     Now the suite refuses to start, at once, with a message that says so.
 *
 *  2. Leftover data. Odoo lines and outbox rows from a failed or aborted run
 *     accumulated, and one test cleaned up by deleting every line dated today
 *     for the employee (which would also delete real entries). Now every line and
 *     row the suite creates carries E2E_PREFIX in its note, and cleanup removes
 *     exactly that — at the start of a run (catching leaks from any earlier
 *     abort) and after every test, in fixture teardown rather than in the test
 *     body.
 */
import { test as base, expect } from "@playwright/test";
import { execFileSync } from "node:child_process";
import path from "node:path";
import { fileURLToPath } from "node:url";

export { expect };

/** Every Odoo line and outbox row the suite creates must start its note with this. */
export const E2E_PREFIX = "e2e-suite";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const REPO_ROOT = path.resolve(__dirname, "../..");
const API_DIR = path.join(REPO_ROOT, "api");

const { ODOO_URL, ODOO_DB, ODOO_USER, ODOO_KEY, POSTGRES_PASSWORD } = process.env;
if (!ODOO_URL || !ODOO_DB || !ODOO_USER || !ODOO_KEY) {
  throw new Error("ODOO_URL/ODOO_DB/ODOO_USER/ODOO_KEY must be set — source ../.env before running the e2e suite");
}

const TM_EMPLOYEE_ID = 1;

async function rpc(service: string, method: string, args: unknown[]): Promise<any> {
  const res = await fetch(`${ODOO_URL}/jsonrpc`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ jsonrpc: "2.0", method: "call", params: { service, method, args }, id: 1 }),
  });
  const body = await res.json();
  if (body.error) throw new Error(JSON.stringify(body.error));
  return body.result;
}

let cachedUid: number | null = null;
async function model(modelName: string, method: string, args: unknown[], kwargs: object = {}): Promise<any> {
  cachedUid ??= (await rpc("common", "authenticate", [ODOO_DB, ODOO_USER, ODOO_KEY, {}])) as number;
  return rpc("object", "execute_kw", [ODOO_DB, cachedUid, ODOO_KEY, modelName, method, args, kwargs]);
}

async function validatedThrough(): Promise<string | false> {
  const [emp] = await model("hr.employee", "read", [[TM_EMPLOYEE_ID]], { fields: ["last_validated_timesheet_date"] });
  return emp.last_validated_timesheet_date || false;
}

function sweepOutbox(): number {
  const out = execFileSync("uv", ["run", "python", "tools/outbox_test_seed.py", "sweep-prefix", E2E_PREFIX], {
    cwd: API_DIR,
    encoding: "utf-8",
    env: {
      ...process.env,
      // .env's DATABASE_URL points at the "db" hostname, which only resolves inside the compose network.
      DATABASE_URL: `postgresql+psycopg://tti:${POSTGRES_PASSWORD}@localhost:5432/tti`,
    },
  });
  return Number(out.trim()) || 0;
}

async function sweepOdooLines(): Promise<number> {
  const ids: number[] = await model("account.analytic.line", "search", [
    [["employee_id", "=", TM_EMPLOYEE_ID], ["name", "=like", `${E2E_PREFIX}%`]],
  ]);
  if (ids.length) await model("account.analytic.line", "unlink", [ids]);
  return ids.length;
}

async function restartApiToDropWarmCaches(): Promise<void> {
  // PeriodService caches the validated-through date for 5 minutes; a direct Odoo write is invisible to it.
  execFileSync("docker", ["compose", "restart", "api"], { cwd: REPO_ROOT });
  for (let i = 0; i < 30; i++) {
    try {
      if ((await fetch("http://localhost/api/healthz")).ok) return;
    } catch {
      // not up yet
    }
    await new Promise((resolve) => setTimeout(resolve, 500));
  }
  throw new Error("api did not become healthy after restart");
}

async function sweepAll(): Promise<void> {
  await sweepOdooLines();
  sweepOutbox();
}

export const test = base.extend<{ cleanAfterTest: void }, { suiteGuard: void }>({
  // Once per worker, before the first test.
  suiteGuard: [
    async ({}, use) => {
      const lock = await validatedThrough();
      if (lock) {
        throw new Error(
          `Employee ${TM_EMPLOYEE_ID} is already locked through ${lock} in Odoo ` +
            `(hr.employee.last_validated_timesheet_date). The suite's lock tests restore whatever lock they find, and ` +
            `every test that needs an open month would time out. If that lock is not deliberate, clear the field and ` +
            `rerun; if it is, leave it alone and do not run this suite against this employee.`,
        );
      }
      await sweepAll(); // leftovers from any earlier aborted run
      await use();
      await sweepAll();
    },
    { scope: "worker", auto: true },
  ],

  // After every test. Teardown runs even when the test failed or timed out,
  // which cleanup inside the test body is not guaranteed to.
  cleanAfterTest: [
    async ({}, use) => {
      await use();
      await sweepAll();
      // The guard proved the lock was unset at the start, so unset is always the right thing to restore.
      if (await validatedThrough()) {
        await model("hr.employee", "write", [[TM_EMPLOYEE_ID], { last_validated_timesheet_date: false }]);
        await restartApiToDropWarmCaches();
      }
    },
    { auto: true },
  ],
});
