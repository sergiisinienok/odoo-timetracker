/**
 * Step 1.6 smoke test: sign in, add an entry, see it listed, confirm in
 * Odoo — run against the real running stack (docker compose up) and the
 * real live Odoo sandbox, no mocking.
 *
 * "Sign in" here bypasses the real Google OAuth screen on purpose: Google
 * actively blocks automated sign-in and it would mean storing real
 * account credentials in a test. The plan's own "Done when" — a real
 * Google account signing in from a phone browser on the real domain — is
 * inherently a by-hand check (like step 1.3's), already verified that
 * way. This test proves everything *after* sign-in concludes: the same
 * session cookie the callback route would have issued, forged here with
 * the same SESSION_SECRET the running api container uses, then the real
 * browser exercises the real frontend against the real backend and the
 * real Odoo sandbox end to end.
 *
 * Requires: docker compose up, and SESSION_SECRET/ODOO_URL/ODOO_DB/
 * ODOO_USER/ODOO_KEY in the environment (e.g. `set -a; source ../.env;
 * set +a` from the repo root before running).
 */
import { test, expect } from "@playwright/test";
import jwt from "jsonwebtoken";

const SESSION_SECRET = process.env.SESSION_SECRET;
const ODOO_URL = process.env.ODOO_URL;
const ODOO_DB = process.env.ODOO_DB;
const ODOO_USER = process.env.ODOO_USER;
const ODOO_KEY = process.env.ODOO_KEY;

if (!SESSION_SECRET || !ODOO_URL || !ODOO_DB || !ODOO_USER || !ODOO_KEY) {
  throw new Error(
    "SESSION_SECRET/ODOO_URL/ODOO_DB/ODOO_USER/ODOO_KEY must be set — " +
      "source ../.env before running `npm run test:e2e`",
  );
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

test("signed-in employee can add an entry through the browser and see it listed", async ({ page, context }) => {
  const token = jwt.sign({ employee_id: 1, timezone: "Europe/Lisbon" }, SESSION_SECRET, {
    algorithm: "HS256",
    expiresIn: "12h",
  });
  await context.addCookies([
    { name: "tti_session", value: token, url: "http://localhost", httpOnly: true, sameSite: "Lax" },
  ]);

  const marker = `Playwright smoke test ${Date.now()}`;

  await page.goto("/");
  await expect(page.getByText(/Signed in as/)).toBeVisible();

  await page.getByLabel("Hours").fill("0.5");
  await page.getByLabel("Note").fill(marker);
  await page.getByRole("button", { name: "Save" }).click();

  await expect(page.getByText(marker)).toBeVisible();

  // Confirm in Odoo, then clean up — the same live sandbox every
  // odoo-marked pytest test in api/tests/odoo/ cleans up after itself.
  const uid = await odooCall("common", "authenticate", [ODOO_DB, ODOO_USER, ODOO_KEY, {}]);
  const ids = (await odooCall("object", "execute_kw", [
    ODOO_DB,
    uid,
    ODOO_KEY,
    "account.analytic.line",
    "search",
    [[["name", "=", marker]]],
  ])) as number[];

  expect(ids.length).toBe(1);

  await odooCall("object", "execute_kw", [ODOO_DB, uid, ODOO_KEY, "account.analytic.line", "unlink", [ids]]);
});
