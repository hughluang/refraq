import fs from "node:fs";
import path from "node:path";

import { expect, type Page } from "@playwright/test";

export const authFile = path.join(process.cwd(), "e2e/.auth/admin.json");

export const adminAccount = process.env.E2E_ADMIN_ACCOUNT ?? "root";
export const adminPassword = process.env.E2E_ADMIN_PASSWORD ?? "change-me";

export async function signIn(page: Page, account: string, password: string) {
  await page.goto("/login");
  await page.getByRole("textbox", { name: "Account" }).fill(account);
  await page.getByRole("textbox", { name: "Password" }).fill(password);
  await page.getByRole("button", { name: "Sign in" }).click();
  await expect(page).toHaveURL(/\/console(?:\/|$|\?)/);
}

export function ensureAuthDir() {
  fs.mkdirSync(path.dirname(authFile), { recursive: true });
}
