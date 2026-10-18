import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

import { defineConfig, devices } from "@playwright/test";

const frontendDir = path.dirname(fileURLToPath(import.meta.url));
const repoRoot = path.resolve(frontendDir, "..");
const venvPython = path.join(repoRoot, "backend/.venv/bin/python");
const python =
  process.env.E2E_PYTHON ??
  (fs.existsSync(venvPython) ? venvPython : "python3");

const apiPort = process.env.E2E_API_PORT ?? "8010";
const consolePort = process.env.E2E_CONSOLE_PORT ?? "4173";
const apiOrigin = `http://127.0.0.1:${apiPort}`;
const consoleOrigin = `http://127.0.0.1:${consolePort}`;

const adminAccount = process.env.E2E_ADMIN_ACCOUNT ?? "root";
const adminPassword = process.env.E2E_ADMIN_PASSWORD ?? "change-me";
const secretsKey =
  process.env.E2E_SECRETS_MASTER_KEY ?? "e2e-secrets-master-key";

const authFile = path.join(frontendDir, "e2e/.auth/admin.json");

export default defineConfig({
  testDir: "./e2e",
  fullyParallel: false,
  workers: 1,
  forbidOnly: !!process.env.CI,
  retries: process.env.CI ? 1 : 0,
  timeout: 60_000,
  expect: { timeout: 15_000 },
  reporter: process.env.CI ? [["github"], ["list"]] : "list",
  use: {
    baseURL: consoleOrigin,
    trace: "retain-on-failure",
    screenshot: "only-on-failure",
  },
  projects: [
    { name: "setup", testMatch: /auth\.setup\.ts/ },
    {
      name: "chromium",
      testIgnore: /auth\.setup\.ts/,
      dependencies: ["setup"],
      use: {
        ...devices["Desktop Chrome"],
        storageState: authFile,
      },
    },
  ],
  webServer: [
    {
      command: `"${python}" -m uvicorn backend.main:app --host 127.0.0.1 --port ${apiPort}`,
      cwd: repoRoot,
      url: `${apiOrigin}/healthz`,
      timeout: 120_000,
      reuseExistingServer: false,
      env: {
        REFRAQ_ENV: "dev",
        REFRAQ_STORE_BACKEND: "memory",
        CELERY_BROKER_URL: "memory://",
        REFRAQ_SECRETS_MASTER_KEY: secretsKey,
        REFRAQ_BROWSER_FACING_HOST: `127.0.0.1:${consolePort}`,
        INITIAL_ADMIN_ACCOUNT: adminAccount,
        INITIAL_ADMIN_PASSWORD: adminPassword,
        TZ: "UTC",
      },
    },
    {
      command: "node e2e/serve-console.mjs",
      cwd: frontendDir,
      url: `${consoleOrigin}/login`,
      timeout: 600_000,
      reuseExistingServer: false,
      env: {
        E2E_CONSOLE_PORT: consolePort,
        REFRAQ_API_UPSTREAM: apiOrigin,
        NEXT_PUBLIC_REFRAQ_API_BASE_URL: "/api",
      },
    },
  ],
});
