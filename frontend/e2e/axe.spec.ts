import { expect, test, type Page } from "@playwright/test";

import { AXE_EXCEPTIONS, expectAccessible } from "./axe";

const pages = [
  { name: "home", path: "/console", ready: /Refraq/ },
  { name: "list", path: "/console/dictionaries", ready: /Dictionaries/ },
  { name: "form", path: "/console/users/new", ready: /New user/ },
] as const;

async function openSignedIn(page: Page, path: string, ready: RegExp) {
  await page.goto(path);
  await expect(page.getByRole("heading", { level: 1, name: ready })).toBeVisible();
}

for (const scheme of ["light", "dark"] as const) {
  test.describe(`axe ${scheme}`, () => {
    test.beforeEach(async ({ page }) => {
      await page.addInitScript((value) => {
        window.localStorage.setItem("mantine-color-scheme-value", value);
      }, scheme);
    });

    for (const target of pages) {
      test(`${target.name} passes WCAG 2.2 AA`, async ({ page }) => {
        await openSignedIn(page, target.path, target.ready);
        await expect(page.locator("html")).toHaveAttribute(
          "data-mantine-color-scheme",
          scheme,
        );
        await expectAccessible(page);
      });
    }

    test("login passes WCAG 2.2 AA", async ({ browser }) => {
      const context = await browser.newContext({
        storageState: { cookies: [], origins: [] },
      });
      await context.addInitScript((value) => {
        window.localStorage.setItem("mantine-color-scheme-value", value);
      }, scheme);
      const page = await context.newPage();
      await page.goto("/login");
      await expect(page.getByRole("button", { name: "Sign in" })).toBeVisible();
      await expect(page.locator("html")).toHaveAttribute(
        "data-mantine-color-scheme",
        scheme,
      );
      await expectAccessible(page);
      await context.close();
    });
  });
}

test("axe exceptions are listed with a reason", () => {
  for (const item of AXE_EXCEPTIONS) {
    expect(item.id.trim().length).toBeGreaterThan(0);
    expect(item.reason.trim().length).toBeGreaterThan(0);
  }
});
