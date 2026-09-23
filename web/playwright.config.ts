import { defineConfig, devices } from "@playwright/test";

export default defineConfig({
  testDir: "./e2e",
  fullyParallel: false,
  // `fullyParallel: false` only serializes tests *within* a file — by
  // default separate spec files still run in separate parallel workers.
  // Every file here shares one live Odoo sandbox employee and restarts
  // the one running `api` container to drop its cache, both global
  // mutable state, so cross-file parallelism silently corrupts runs
  // (discovered running the full e2e/ suite together for step 2.6).
  workers: 1,
  retries: 0,
  reporter: "list",
  use: {
    baseURL: "http://localhost",
    trace: "retain-on-failure",
  },
  projects: [{ name: "chromium", use: { ...devices["Desktop Chrome"] } }],
});
