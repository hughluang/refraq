import { expect, test, type Page } from "@playwright/test";

import { createDatabaseSource, createRole, createUser, patchProfile, stamp } from "./api";
import { signIn } from "./auth";

const nav = (page: Page) => page.getByRole("navigation", { name: "Modules" });

test("sign-in lands on console home and the rail choice survives reload", async ({
  page,
}) => {
  await page.goto("/console");
  await expect(page.getByRole("heading", { level: 1, name: "Refraq" })).toBeVisible();
  const home = nav(page).getByRole("link", { name: "Home" });
  await expect(home).toHaveAttribute("aria-current", "page");
  await expect(home.locator("svg")).toBeVisible();
  const users = nav(page).getByRole("link", { name: "Users" });
  await expect(users.locator("svg")).toBeVisible();

  await page.getByRole("button", { name: "Collapse navigation" }).click();
  await page.reload();
  await expect(page.getByRole("button", { name: "Expand navigation" })).toHaveAttribute(
    "aria-pressed",
    "true",
  );
});

test("palette jumps to a module and lists a visited record under Recent", async ({
  page,
  request,
}) => {
  const mark = stamp();
  const displayName = `Zinnia ${mark}`;
  await createUser(request, {
    account: `zinnia${mark}`,
    display_name: displayName,
    password: "e2e-pass-1",
    role_id: null,
  });

  await page.goto("/console");
  await page.keyboard.press("Control+K");
  const palette = page.getByRole("dialog");
  await palette.getByRole("textbox", { name: "Search" }).fill("Dictionaries");
  await palette.getByRole("button", { name: "Dictionaries", exact: true }).click();
  await expect(page).toHaveURL(/\/console\/dictionaries$/);

  await page.keyboard.press("Control+K");
  await palette.getByRole("textbox", { name: "Search" }).fill(displayName);
  await palette.getByRole("button", { name: displayName }).click();
  await expect(page).toHaveURL(/\/console\/users\//);
  await expect(page.getByRole("heading", { level: 1, name: displayName })).toBeVisible();

  await page.keyboard.press("Control+K");
  await expect(palette.getByText("Recent", { exact: true })).toBeVisible();
  await expect(palette.getByRole("button", { name: displayName }).first()).toBeVisible();
});

test("dictionary list search and filter stay in the URL and the empty state offers create", async ({
  page,
}) => {
  await page.goto("/console/dictionaries");
  await expect(
    page.getByText("Create a dictionary to share a named set of values."),
  ).toBeVisible();
  await expect(page.getByRole("link", { name: "New dictionary" }).first()).toBeVisible();

  const before = await page.evaluate(() => window.history.length);
  await page.getByRole("textbox", { name: "Search" }).fill("missing-dictionary");
  await page.getByRole("textbox", { name: "Search" }).press("Enter");
  await expect(page).toHaveURL(/[?&]q=missing-dictionary/);
  expect(await page.evaluate(() => window.history.length)).toBe(before);

  await page.getByRole("combobox", { name: "Status" }).click({ force: true });
  await page.getByRole("option", { name: "Deprecated" }).click();
  await page.keyboard.press("Escape");
  await expect(page).toHaveURL(/status=deprecated/);
  expect(await page.evaluate(() => window.history.length)).toBe(before);

  await page.reload();
  await expect(page.getByRole("textbox", { name: "Search" })).toHaveValue(
    "missing-dictionary",
  );
  await expect(page).toHaveURL(/status=deprecated/);

  await page.getByRole("button", { name: "Clear Filters" }).first().click();
  await expect(page).not.toHaveURL(/[?&]q=/);
  await expect(page).not.toHaveURL(/status=/);
  await expect(page.getByRole("textbox", { name: "Search" })).toHaveValue("");
  await expect(
    page.getByText("Create a dictionary to share a named set of values."),
  ).toBeVisible();
});

test("server validation focuses the field, then save confirms and the header action stays put", async ({
  page,
  request,
}) => {
  await page.setViewportSize({ width: 1100, height: 520 });
  await page.goto("/console/account");
  const email = page.getByRole("textbox", { name: "Email" });
  const save = page.getByRole("button", { name: "Save profile" });
  await email.fill("a".repeat(257));
  await save.click();
  await expect(email).toBeFocused();
  await expect(email).toHaveAttribute("aria-invalid", "true");
  await expect(page.getByText(/256/)).toBeVisible();

  await email.fill("e2e-admin@example.com");
  await save.click();
  await expect(page.getByText("Profile updated")).toBeVisible();

  const before = await save.boundingBox();
  await page.locator("[data-page-scroll]").evaluate((node) => {
    node.scrollTop = node.scrollHeight;
  });
  const after = await save.boundingBox();
  expect(after?.y).toBe(before?.y);
  expect(after!.y).toBeGreaterThanOrEqual(0);
  expect(after!.y + after!.height).toBeLessThanOrEqual(520);

  await patchProfile(request, { email: null });
});

test("a dirty form asks before leaving and Stay keeps the draft", async ({ page }) => {
  const account = `draft${stamp()}`;
  await page.goto("/console/users/new");
  await page.getByRole("textbox", { name: "Account" }).fill(account);
  await nav(page).getByRole("link", { name: "Home" }).click();
  const dialog = page.getByRole("dialog", { name: "Discard unsaved changes?" });
  await expect(dialog).toBeVisible();
  await dialog.getByRole("button", { name: "Stay" }).click();
  await expect(dialog).toBeHidden();
  await expect(page.getByRole("textbox", { name: "Account" })).toHaveValue(account);
  await expect(page).toHaveURL(/\/console\/users\/new$/);

  await nav(page).getByRole("link", { name: "Home" }).click();
  await page
    .getByRole("dialog", { name: "Discard unsaved changes?" })
    .getByRole("button", { name: "Discard" })
    .click();
  await expect(page).toHaveURL(/\/console\/?$/);
  await expect(page.getByRole("heading", { level: 1, name: "Refraq" })).toBeVisible();
});

test("delete asks for confirmation that names the record", async ({ page, request }) => {
  const mark = stamp();
  const name = `E2E role ${mark}`;
  await createRole(request, {
    key: `e2erole${mark}`,
    name,
    permissions: ["console:access"],
  });
  await page.goto("/console/roles");
  const row = page.getByRole("row", { name });
  await row.getByRole("button", { name: "Delete" }).click();
  const dialog = page.getByRole("dialog");
  await expect(dialog).toContainText(name);
  await expect(dialog).toContainText("This cannot be undone.");
  await dialog.getByRole("button", { name: "Delete" }).click();
  await expect(page.getByRole("row", { name })).toHaveCount(0);
});

test("a scheduled task toggle offers Undo and Undo restores it", async ({
  page,
  request,
}) => {
  const key = `e2esrc${stamp()}`;
  await createDatabaseSource(request, { key, name: key });
  await page.goto("/console/schedules");
  const row = page.getByRole("row").filter({ hasText: `structure · ${key}` });
  const toggle = row.getByRole("switch");
  await expect(toggle).toBeChecked();
  await toggle.click({ force: true });
  await expect(toggle).not.toBeChecked();
  await page.getByRole("button", { name: "Undo" }).click();
  await expect(toggle).toBeChecked();
  await expect(page.getByText(`Undone — structure · ${key}`)).toBeVisible();
});

test("an unknown console path is not found inside the shell", async ({ page }) => {
  await page.goto("/console/not-a-registered-module");
  await expect(page.getByRole("heading", { name: "Page not found" })).toBeVisible();
  await expect(nav(page).getByRole("link", { name: "Home" })).toBeVisible();
});

test("a restricted user sees the forbidden state naming the module", async ({
  browser,
  request,
}) => {
  const mark = stamp();
  const account = `limited${mark}`;
  const password = "e2e-pass-1";
  await createUser(request, {
    account,
    display_name: `Limited ${mark}`,
    password,
    role_id: "role_operator",
  });
  const context = await browser.newContext({
    storageState: { cookies: [], origins: [] },
  });
  const page = await context.newPage();
  await signIn(page, account, password);
  await page.goto("/console/users");
  await expect(page.getByText("You do not have access to Users.")).toBeVisible();
  await expect(nav(page)).toBeVisible();
  await context.close();
});

test("color scheme persists across reload without a wrong-scheme first frame", async ({
  page,
}) => {
  await page.addInitScript(() => {
    const win = window as Window & { __e2eFirstFrame?: string | null };
    const capture = () => {
      if (win.__e2eFirstFrame !== undefined) return;
      win.__e2eFirstFrame = document.documentElement.getAttribute(
        "data-mantine-color-scheme",
      );
    };
    requestAnimationFrame(capture);
  });
  await page.goto("/console");
  await page.getByRole("button", { name: "Color scheme" }).click();
  await page.getByRole("menuitem", { name: "Dark" }).click();
  await expect(page.locator("html")).toHaveAttribute("data-mantine-color-scheme", "dark");

  await page.reload();
  await expect(page.locator("html")).toHaveAttribute("data-mantine-color-scheme", "dark");
  const firstFrame = await page.evaluate(
    () =>
      (window as Window & { __e2eFirstFrame?: string | null }).__e2eFirstFrame ?? null,
  );
  expect(firstFrame).toBe("dark");
  await expect(page.getByRole("button", { name: "Color scheme" })).toContainText("Dark");
});

test("navigation updates the document title and moves focus to the page heading", async ({
  page,
}) => {
  await page.goto("/console");
  await nav(page).getByRole("link", { name: "Users" }).click();
  const heading = page.getByRole("heading", { level: 1, name: "Users" });
  await expect(heading).toBeFocused();
  await expect(page).toHaveTitle("Users · Refraq");
});

test("the phone navigation overlay closes after navigation", async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto("/console");
  await page.getByRole("button", { name: "Modules" }).click();
  const users = nav(page).getByRole("link", { name: "Users" });
  await expect(users).toBeVisible();
  await users.click();
  await expect(page).toHaveURL(/\/console\/users$/);
  await expect(page.getByRole("heading", { level: 1, name: "Users" })).toBeVisible();
  await expect.poll(async () => {
    const box = await users.boundingBox();
    return box === null || box.x + box.width <= 0;
  }).toBe(true);
});
