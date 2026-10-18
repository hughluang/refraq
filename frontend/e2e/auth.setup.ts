import { test as setup } from "@playwright/test";

import { adminAccount, adminPassword, authFile, ensureAuthDir, signIn } from "./auth";

setup("sign in as the initial administrator", async ({ page }) => {
  ensureAuthDir();
  await signIn(page, adminAccount, adminPassword);
  await page.context().storageState({ path: authFile });
});
