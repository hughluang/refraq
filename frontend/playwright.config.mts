import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

import { defineConfig, devices } from "@playwright/test";

const frontendDir = path.dirname(fileURLToPath(import.meta.url));
const repoRoot = path.resolve(frontendDir, "..");
const venvPython = [".venv/bin/python", "backend/.venv/bin/python"]
  .map((candidate) => path.join(repoRoot, candidate))
  .find((candidate) => fs.existsSync(candidate));
const python =
  process.env.E2E_PYTHON ?? venvPython ?? "python3";
const salesJourney = process.env.E2E_CDC_JOURNEY === "1";
const authSetup = /auth\.setup\.ts/;
const salesSpec = /cdc-console-journey\.spec\.ts/;

// Keep direct fixture launchers supported alongside Python interpreter overrides.
const apiLauncher = python.endsWith(".py") ? `"${python}"` : `"${python}" frontend/e2e/catalog-relations-api.py`;

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
    { name: "setup", testMatch: authSetup },
    {
      name: "chromium",
      ...(salesJourney ? { testMatch: salesSpec } : { testIgnore: [authSetup, salesSpec] }),
      dependencies: ["setup"],
      use: {
        ...devices["Desktop Chrome"],
        storageState: authFile,
      },
    },
  ],
  webServer: [
    {
      command: `${apiLauncher} -m uvicorn backend.main:app --host 127.0.0.1 --port ${apiPort}`,
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
        E2E_CDC_JOURNEY: salesJourney ? "1" : "0",
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
