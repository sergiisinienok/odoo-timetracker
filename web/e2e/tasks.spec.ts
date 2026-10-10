/**
 * Step 2b.8: logging against a project and a task.
 *
 * Same sign-in bypass as month-view.spec.ts. Every task and line a test creates
 * carries E2E_PREFIX (see fixtures.ts), so the fixtures remove them. The catalog
 * is cached for 60 s in the api, so each test restarts it after seeding.
 */
import { E2E_PREFIX, createLine, createTask, expect, model, restartApiToDropWarmCaches, test } from "./fixtures";
import jwt from "jsonwebtoken";

const SESSION_SECRET = process.env.SESSION_SECRET;
if (!SESSION_SECRET) throw new Error("SESSION_SECRET must be set — source ../.env before running `npm run test:e2e`");

const TM_EMPLOYEE_ID = 1;
const T_AND_M = 2; // S00001, billable, employee 1 mapped — "Alpha Inc - Test"
const FLAT_RATE = 28; // Beta INC Effort Project, employee 1 mapped — "Beta Inc - Test"

function isoDate(d: Date): string {
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
}
const TODAY = isoDate(new Date());

async function signIn(context: import("@playwright/test").BrowserContext) {
  const value = jwt.sign({ employee_id: TM_EMPLOYEE_ID, timezone: "Europe/Lisbon" }, SESSION_SECRET!, {
    algorithm: "HS256",
    expiresIn: "12h",
  });
  await context.addCookies([{ name: "tti_session", value, url: "http://localhost", httpOnly: true, sameSite: "Lax" }]);
}

async function lineOf(id: number) {
  const [line] = await model("account.analytic.line", "read", [[id]], {
    fields: ["task_id", "project_id", "so_line", "unit_amount", "is_so_line_edited"],
  });
  return line;
}

test("logs against the pre-filled task", async ({ page, context }) => {
  const taskId = await createTask(T_AND_M, "prefilled task");
  await createLine({ projectId: T_AND_M, taskId, date: TODAY, hours: 0.25, note: "prefill seed" });
  await restartApiToDropWarmCaches();

  await signIn(context);
  await page.goto("/");
  await page.getByLabel("Project").selectOption(String(T_AND_M));
  await expect(page.getByLabel("Task")).toHaveValue(String(taskId));

  await page.getByRole("spinbutton", { name: "Hours" }).fill("1");
  await page.getByPlaceholder("Note (optional)").fill(`${E2E_PREFIX} logged on the prefilled task`);
  await page.getByRole("button", { name: "Save entry" }).click();
  await expect(page.getByText(/Entry saved|Waiting for Odoo/)).toBeVisible();

  const [saved] = await model("account.analytic.line", "search_read", [
    [["employee_id", "=", TM_EMPLOYEE_ID], ["name", "=", `${E2E_PREFIX} logged on the prefilled task`]],
  ], { fields: ["task_id"] });
  expect(saved.task_id[0]).toBe(taskId);
});

test("changing the project re-fills the task", async ({ page, context }) => {
  const taskA = await createTask(T_AND_M, "task on the T&M project");
  const taskB = await createTask(FLAT_RATE, "task on the flat-rate project");
  await createLine({ projectId: T_AND_M, taskId: taskA, date: TODAY, hours: 0.25, note: "refill seed A" });
  await createLine({ projectId: FLAT_RATE, taskId: taskB, date: TODAY, hours: 0.25, note: "refill seed B" });
  await restartApiToDropWarmCaches();

  await signIn(context);
  await page.goto("/");
  const task = page.getByLabel("Task");

  await page.getByLabel("Project").selectOption(String(T_AND_M));
  await expect(task).toHaveValue(String(taskA));
  await page.getByLabel("Project").selectOption(String(FLAT_RATE));
  await expect(task).toHaveValue(String(taskB));
  await page.getByLabel("Project").selectOption(String(T_AND_M));
  await expect(task).toHaveValue(String(taskA));
});

test("a closed task is not offered", async ({ page, context }) => {
  const openId = await createTask(T_AND_M, "open task");
  await createTask(T_AND_M, "closed task", { state: "1_done" });
  await restartApiToDropWarmCaches();

  await signIn(context);
  await page.goto("/");
  await page.getByLabel("Project").selectOption(String(T_AND_M));

  const options = await page.getByLabel("Task").locator("option").allTextContents();
  expect(options).toContain(`${E2E_PREFIX} open task`);
  expect(options).not.toContain(`${E2E_PREFIX} closed task`);
  expect(openId).toBeGreaterThan(0);
});

test("editing a legacy line forces a task to be picked", async ({ page, context }) => {
  const taskId = await createTask(T_AND_M, "adopts the legacy line");
  const legacyId = await createLine({ projectId: T_AND_M, date: TODAY, hours: 1, note: "legacy line without a task" });
  await restartApiToDropWarmCaches();

  await signIn(context);
  await page.goto("/");
  await page.getByRole("button", { name: "Expand day" }).first().click();
  await expect(page.getByText("No task").first()).toBeVisible();
  await page.getByRole("button", { name: "Edit" }).first().click();

  const taskPicker = page.getByLabel("Edit task");
  await expect(taskPicker).toHaveValue("");
  await expect(page.getByRole("button", { name: "Save changes" })).toBeDisabled();

  await taskPicker.selectOption(String(taskId));
  await page.getByRole("button", { name: "Save changes" }).click();
  await expect(page.getByLabel("Edit task")).toHaveCount(0);

  expect((await lineOf(legacyId)).task_id[0]).toBe(taskId);
});

test("an approver's override is explained in plain words, not refused with a code", async ({ page, context }) => {
  const taskA = await createTask(T_AND_M, "overridden line's task");
  const taskB = await createTask(T_AND_M, "task the employee tries to move to");
  const lineId = await createLine({ projectId: T_AND_M, taskId: taskA, date: TODAY, hours: 1, note: "overridden line" });
  // What the Odoo UI does when an approver changes a line's Sales Order Item.
  await model("account.analytic.line", "write", [[lineId], { is_so_line_edited: true }]);
  await restartApiToDropWarmCaches();

  await signIn(context);
  await page.goto("/");
  await page.getByRole("button", { name: "Expand day" }).first().click();
  await page.getByRole("button", { name: "Edit" }).first().click();
  await page.getByLabel("Edit task").selectOption(String(taskB));
  await page.getByRole("button", { name: "Save changes" }).click();

  await expect(page.getByRole("alert")).toHaveText("The approver has set how this line is billed. Ask them to move it.");
  expect((await lineOf(lineId)).task_id[0]).toBe(taskA); // untouched
});

test("history filters by project and task", async ({ page, context }) => {
  const taskA = await createTask(T_AND_M, "history task A");
  const taskB = await createTask(T_AND_M, "history task B");
  const taskC = await createTask(FLAT_RATE, "history task C");
  await createLine({ projectId: T_AND_M, taskId: taskA, date: TODAY, hours: 0.25, note: "history note on A" });
  await createLine({ projectId: T_AND_M, taskId: taskB, date: TODAY, hours: 0.25, note: "history note on B" });
  await createLine({ projectId: FLAT_RATE, taskId: taskC, date: TODAY, hours: 0.25, note: "history note on C" });
  await restartApiToDropWarmCaches();

  await signIn(context);
  await page.goto("/");
  await page.getByRole("button", { name: "Time tracking" }).click();
  await page.getByLabel("Search notes").fill(`${E2E_PREFIX} history note`);
  await expect(page.getByText("3 entries")).toBeVisible();

  await page.getByLabel("Project filter").selectOption(String(T_AND_M));
  await expect(page.getByText("2 entries")).toBeVisible();
  await expect(page.getByText(`${E2E_PREFIX} history note on C`)).toHaveCount(0);

  await page.getByLabel("Task filter").selectOption(String(taskB));
  await expect(page.getByText("1 entry")).toBeVisible();
  await expect(page.getByText(`${E2E_PREFIX} history note on B`)).toBeVisible();
  await expect(page.locator(".history-row").getByText(`${E2E_PREFIX} history task B`)).toBeVisible(); // the row names its task
});

test("logs time on an unbillable project the employee is not mapped to", async ({ page, context }) => {
  // Project 33 is unbillable and employee 1 has no mapping on it (decision 0014): open to everyone.
  const UNBILLABLE_UNMAPPED = 33;
  const taskId = await createTask(UNBILLABLE_UNMAPPED, "task on an unmapped unbillable project");
  await restartApiToDropWarmCaches();

  await signIn(context);
  await page.goto("/");
  // Chosen directly by the project's own name — there is no "Internal" shortcut.
  await page.getByLabel("Project").selectOption({ label: "Internal project (not billable, no mapping)" });
  await page.getByLabel("Task").selectOption(String(taskId));
  await page.getByRole("spinbutton", { name: "Hours" }).fill("0.25");
  await page.getByPlaceholder("Note (optional)").fill(`${E2E_PREFIX} unbillable, unmapped`);
  await page.getByRole("button", { name: "Save entry" }).click();
  await expect(page.getByText(/Entry saved|Waiting for Odoo/)).toBeVisible();

  const [saved] = await model("account.analytic.line", "search_read", [
    [["employee_id", "=", TM_EMPLOYEE_ID], ["name", "=", `${E2E_PREFIX} unbillable, unmapped`]],
  ], { fields: ["task_id", "project_id", "so_line"] });
  expect(saved.project_id[0]).toBe(UNBILLABLE_UNMAPPED);
  expect(saved.task_id[0]).toBe(taskId);
  expect(saved.so_line).toBe(false);
});
