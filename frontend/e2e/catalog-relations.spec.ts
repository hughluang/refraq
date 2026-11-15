import { expect, test, type APIRequestContext, type Locator, type Page } from "@playwright/test";
import en from "../src/locales/en-US/common.json";
import zh from "../src/locales/zh-CN/common.json";
import { expectAccessible } from "./axe";

// Run with E2E_PYTHON=$PWD/e2e/catalog-relations-api.py and the existing config.
// The fixture seeds collected objects only; reads, writes and refusals use the real API.
const remoteName = "customer_accounts_with_a_deliberately_long_catalog_object_name";
const objectId = (caseName: string, name = "orders") => `relations-${caseName}-${name}`;
const url = (caseName: string) => `/console/catalog/${objectId(caseName)}?tab=joins`;
const dialog = (page: Page) => page.getByRole("region", { name: en["catalog.joins.add"], exact: true });
const row = (page: Page, column = "id") => page.getByRole("row").filter({ hasText: `orders.${column}` });

async function choose(page: Page, scope: Locator, label: string, option: string | RegExp) {
  await scope.getByRole("combobox", { name: label, exact: true }).click();
  await page.getByRole("option", { name: option, exact: typeof option === "string" }).click();
}

async function expectDraftConnector(form: Locator, incoming: boolean) {
  await expect(form.locator("svg[data-draft-connector] > path")).toHaveCount(1);
  await expect.poll(() => form.evaluate((root, reversed) => {
    const local = root.querySelector('[data-draft-port="local"]')!.getBoundingClientRect();
    const remote = root.querySelector('[data-draft-port="remote"]')!.getBoundingClientRect();
    const path = root.querySelector<SVGPathElement>('svg[data-draft-connector] > path')!;
    const matrix = path.getScreenCTM()!;
    const start = path.getPointAtLength(0).matrixTransform(matrix);
    const end = path.getPointAtLength(path.getTotalLength()).matrixTransform(matrix);
    const stacked = remote.top > local.bottom && remote.left < local.right;
    const a = { x: local.right, y: local.top + local.height / 2 };
    const b = { x: stacked ? remote.right : remote.left, y: remote.top + remote.height / 2 };
    const from = reversed ? b : a;
    const to = reversed ? a : b;
    const svg = root.querySelector('svg[data-draft-connector]')!.getBoundingClientRect();
    const bounds = path.getBBox();
    return Math.max(Math.abs(start.x - from.x), Math.abs(start.y - from.y), Math.abs(end.x - to.x), Math.abs(end.y - to.y), -bounds.x, -bounds.y, bounds.x + bounds.width - svg.width, bounds.y + bounds.height - svg.height);
  }, incoming)).toBeLessThan(2);
}

async function seedJoin(request: APIRequestContext, caseName: string, incoming = false) {
  const local = `${objectId(caseName)}-id`;
  const remote = `${objectId(caseName, remoteName)}-alternate_id`;
  const result = await request.post("/api/joins", { data: {
    from_column_id: incoming ? remote : local,
    to_column_id: incoming ? local : remote,
    join_kind: "LEFT", join_expression: "remote.alternate_id = orders.id",
    evidence: "Browser integration fixture: documented customer identifier mapping",
  } });
  expect(result.ok(), await result.text()).toBeTruthy();
  return (await result.json()).join;
}

async function fillCreate(page: Page, incoming: boolean) {
  const form = dialog(page);
  await expect(form.getByRole("combobox", { name: "Current column", exact: true })).toHaveValue("");
  if (incoming) await choose(page, form, "Direction", en["catalog.joins.incomingCreate"]);
  await choose(page, form, "Current column", "id · integer");
  const sourceKey = new URL(page.url()).pathname.includes("relations-author-") ? "relations-author" : "relations-failure";
  await expect(form.getByRole("textbox", { name: "Search objects", exact: true })).toHaveCount(0);
  await form.getByRole("combobox", { name: "Other object", exact: true }).fill(`obj/postgresql/${sourceKey}/public/table/${remoteName}`);
  await choose(page, form, "Other object", new RegExp(`obj/postgresql/${sourceKey}/public/table/${remoteName}$`));
  await expect(form.getByRole("combobox", { name: "Other column", exact: true })).toHaveValue("");
  await choose(page, form, "Other column", "alternate_id · integer");
  await choose(page, form, "Join kind", "LEFT");
  await form.getByRole("textbox", { name: "Evidence", exact: true }).fill("Explicit browser-authored identifier mapping");
}

for (const incoming of [false, true]) {
  test(`creates ${incoming ? "incoming" : "outgoing"} with stored endpoint order`, async ({ page, request }) => {
    // Separate directed pairs in one isolated source permit both orientations.
    await page.goto(url("author"));
    await page.getByRole("button", { name: "Add relation", exact: true }).first().click();
    await fillCreate(page, incoming);
    await expect(dialog(page).getByRole("status")).toContainText(incoming ? `${remoteName}.alternate_id → orders.id` : `orders.id → ${remoteName}.alternate_id`);
    await expect(page.getByRole("dialog")).toHaveCount(0);
    await expectDraftConnector(dialog(page), incoming);
    await dialog(page).getByRole("button", { name: "Swap draft direction" }).click();
    await expectDraftConnector(dialog(page), !incoming);
    await expect(dialog(page).getByRole("status")).toContainText(incoming ? `orders.id → ${remoteName}.alternate_id` : `${remoteName}.alternate_id → orders.id`);
    await dialog(page).getByRole("button", { name: "Swap draft direction" }).click();
    await expectDraftConnector(dialog(page), incoming);
    await page.setViewportSize({ width: 1280, height: 1000 });
    await dialog(page).locator('[data-draft-port="local"]').scrollIntoViewIfNeeded();
    await expectDraftConnector(dialog(page), incoming);
    await page.screenshot({ path: test.info().outputPath("relations-builder.png"), fullPage: true });
    const response = page.waitForResponse((r) => r.url().endsWith("/api/joins") && r.request().method() === "POST");
    await dialog(page).getByRole("button", { name: "Create relation", exact: true }).click();
    const saved = await response;
    expect(saved.status(), await saved.text()).toBe(201);
    const { join } = await saved.json();
    expect(join.from_column_id).toBe(`${objectId("author", incoming ? remoteName : "orders")}-${incoming ? "alternate_id" : "id"}`);
    expect(join.to_column_id).toBe(`${objectId("author", incoming ? "orders" : remoteName)}-${incoming ? "id" : "alternate_id"}`);
    await expect(dialog(page)).toBeHidden();
    await expect(page).toHaveURL(/tab=joins/);
    await expect(row(page).filter({ hasText: incoming ? "Incoming" : "Outgoing" })).toHaveCount(1);
    const stored = await request.get(`/api/objects/${objectId("author")}/joins`);
    expect((await stored.json()).items.some((item: { id: string }) => item.id === join.id)).toBe(true);
  });
}

test("object selector supports keyboard search, close restoration and endpoint clearing", async ({ page }) => {
  const queries: string[] = [];
  page.on("request", (request) => {
    if (request.url().includes("/api/catalog/objects/search?")) queries.push(new URL(request.url()).searchParams.get("q") ?? "");
  });
  await page.goto(url("paths"));
  await page.getByRole("button", { name: "Add relation", exact: true }).first().click();
  const form = dialog(page);
  const other = form.getByRole("combobox", { name: "Other object", exact: true });
  await expect(form.getByRole("textbox", { name: "Search objects", exact: true })).toHaveCount(0);
  const locator = `obj/postgresql/relations-paths/public/table/${remoteName}`;
  await other.fill(locator);
  const candidate = page.getByRole("option", { name: new RegExp(`${locator}$`) });
  await expect(candidate).toBeVisible();
  const label = await candidate.textContent();
  await other.press("ArrowDown");
  await other.press("ArrowDown");
  await other.press("Enter");
  await expect(other).toHaveValue(label!);
  await choose(page, form, "Other column", "alternate_id · integer");
  await other.fill("unfinished query");
  await other.press("Escape");
  await expect(form).toBeVisible();
  await expect(other).toHaveValue(label!);
  await expect(form.getByRole("combobox", { name: "Other column", exact: true })).toHaveValue("alternate_id · integer");
  await other.click();
  await expect(page.getByRole("option", { name: label!, exact: true })).toBeVisible();
  await other.locator("..").getByRole("button").click();
  await expect(other).toHaveValue("");
  await expect(other).toHaveAttribute("placeholder", "Search by name or locator");
  await expect(form.getByRole("combobox", { name: "Other column", exact: true })).toHaveCount(0);
  await other.click();
  await expect(page.getByRole("option", { name: /\/public\/table\/orders$/ })).toBeVisible();
  await expect(page.getByRole("option", { name: label!, exact: true })).toHaveCount(0);
  await other.fill("discard before debounce");
  await other.press("Escape");
  await expect(other).toHaveValue("");
  await page.waitForTimeout(400);
  expect(queries).toEqual([locator]);
});

test("graph column prefills a draft and swapped preview saves the exact same-object order", async ({ page }) => {
  await page.goto(url("paths"));
  const graph = page.getByRole("region", { name: "Relation graph", exact: true });
  await graph.getByRole("button", { name: "foreign_id", exact: false }).click();
  const posts: unknown[] = [];
  page.on("request", (request) => { if (request.url().endsWith("/api/joins") && request.method() === "POST") posts.push(request.postDataJSON()); });
  await page.getByRole("button", { name: "Add relation", exact: true }).first().click();
  const form = dialog(page);
  await expect(form.getByRole("combobox", { name: "Current column", exact: true })).toHaveValue("foreign_id · integer");
  await choose(page, form, "Other object", /\/public\/table\/orders$/);
  await choose(page, form, "Other column", "alternate_id · integer");
  await expectDraftConnector(form, false);
  await form.getByRole("button", { name: "Swap draft direction" }).click();
  await expect(form.getByRole("status")).toHaveText("Draft: orders.alternate_id → orders.foreign_id");
  await expectDraftConnector(form, true);
  await page.setViewportSize({ width: 390, height: 520 });
  await expectDraftConnector(form, true);
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth + 1)).toBe(true);
  await form.locator('[data-draft-port="remote"]').scrollIntoViewIfNeeded();
  await page.screenshot({ path: test.info().outputPath("relations-builder-narrow.png"), fullPage: true });
  expect(posts).toHaveLength(0);
  await form.getByRole("textbox", { name: "Evidence", exact: true }).fill("Explicit graph-prefilled swapped mapping");
  const response = page.waitForResponse((r) => r.url().endsWith("/api/joins") && r.request().method() === "POST");
  await form.getByRole("button", { name: "Create relation", exact: true }).click();
  expect((await response).status()).toBe(201);
  expect(posts).toEqual([{ from_column_id: `${objectId("paths")}-alternate_id`, to_column_id: `${objectId("paths")}-foreign_id`, evidence: "Explicit graph-prefilled swapped mapping", join_kind: "INNER", join_expression: null }]);
  await expect(form).toBeHidden();
});

test("incoming edit has immutable endpoints and dirty Escape preserves then discards draft", async ({ page, request }) => {
  const join = await seedJoin(request, "edit", true);
  await page.goto(url("edit"));
  const edit = row(page).getByRole("button", { name: "Edit", exact: true });
  await edit.focus();
  await page.keyboard.press("Enter");
  const form = page.getByRole("region", { name: "Editing join", exact: true });
  await expect(form.getByRole("combobox", { name: "Join kind", exact: true })).toBeFocused();
  await expect(form.getByRole("combobox", { name: "Current column", exact: true })).toHaveCount(0);
  await expect(form.getByRole("combobox", { name: "Other object", exact: true })).toHaveCount(0);
  await expect(form.getByRole("combobox", { name: "Other column", exact: true })).toHaveCount(0);
  await expect(form.getByRole("link").first()).toHaveText(`${remoteName}.alternate_id`);
  const evidence = form.getByRole("textbox", { name: "Evidence", exact: true });
  await evidence.fill("Retained amended evidence");
  await page.keyboard.press("Escape");
  const guard = page.getByRole("dialog", { name: "Discard unsaved changes?" });
  await guard.getByRole("button", { name: "Stay", exact: true }).click();
  await expect(evidence).toHaveValue("Retained amended evidence");
  const response = page.waitForResponse((r) => r.url().endsWith(`/api/joins/${join.id}`) && r.request().method() === "PATCH");
  await form.getByRole("button", { name: "Save relation", exact: true }).click();
  const patched = await response;
  expect(patched.ok(), await patched.text()).toBeTruthy();
  expect(patched.request().postDataJSON()).toEqual({ evidence: "Retained amended evidence", join_kind: "LEFT", join_expression: join.join_expression });
  await expect(form).toBeHidden();
  await expect.soft(edit).toBeFocused();
  await edit.click();
  await evidence.fill("Discard this draft");
  await form.getByRole("button", { name: "Cancel", exact: true }).click();
  await guard.getByRole("button", { name: "Discard", exact: true }).click();
  await edit.click();
  await expect(evidence).toHaveValue("Retained amended evidence");
});

test("named lifecycle confirmations focus Cancel and enforce manual/automatic/rejected policy", async ({ page, request }) => {
  await seedJoin(request, "lifecycle");
  await page.goto(url("lifecycle"));
  const manual = row(page);
  const more = manual.getByRole("button").last();
  await more.focus();
  await page.keyboard.press("Enter");
  await page.getByRole("menuitem", { name: "Reject", exact: true }).click();
  const confirm = page.getByRole("dialog");
  await expect(confirm).toContainText("orders.id");
  await expect(confirm).toContainText(`${remoteName}.alternate_id`);
  await expect(confirm).toContainText("durably suppressed");
  await expect(confirm.getByRole("button", { name: "Cancel", exact: true })).toBeFocused();
  await page.keyboard.press("Escape");
  await expect(confirm).toBeHidden();
  await expect.soft(more).toBeFocused();
  await more.click();
  await page.getByRole("menuitem", { name: "Reject", exact: true }).click();
  await confirm.getByRole("button", { name: "Reject", exact: true }).click();
  await expect(manual).toContainText("Rejected");
  await expect(manual.getByRole("button", { name: "Edit", exact: true })).toHaveCount(0);
  await expect(manual.getByRole("button")).toHaveCount(2);
  await manual.getByRole("button", { name: "Restore", exact: true }).click();
  await expect(manual).not.toContainText("Rejected");
  await more.click();
  await page.getByRole("menuitem", { name: "Delete", exact: true }).click();
  await expect(confirm).toContainText("automatic discovery may insert the pair again");
  await expect(confirm).toContainText("This cannot be undone.");
  await expect(confirm.getByRole("button", { name: "Cancel", exact: true })).toBeFocused();
  await confirm.getByRole("button", { name: "Delete", exact: true }).click();
  await expect(manual).toHaveCount(0);
  const automatic = row(page, "foreign_id");
  await expect(automatic).toContainText("Automated");
  await automatic.getByRole("button").last().click();
  await expect(page.getByRole("menuitem", { name: "Reject", exact: true })).toBeVisible();
  await expect(page.getByRole("menuitem", { name: "Delete", exact: true })).toHaveCount(0);
});

test("real duplicate refusal keeps draft and succeeds after removing the conflicting pair", async ({ page, request }) => {
  const join = await seedJoin(request, "failure");
  await page.goto(url("failure"));
  await page.getByRole("button", { name: "Add relation", exact: true }).first().click();
  await fillCreate(page, false);
  const response = page.waitForResponse((r) => r.url().endsWith("/api/joins") && r.request().method() === "POST");
  await dialog(page).getByRole("button", { name: "Create relation", exact: true }).click();
  const refused = await response;
  expect(refused.ok()).toBe(false);
  expect((await refused.json()).code).toBe("JOIN_ALREADY_DEFINED");
  await expect(dialog(page).getByRole("alert")).toBeVisible();
  await expect(dialog(page).getByRole("textbox", { name: "Evidence", exact: true })).not.toHaveAttribute("aria-invalid", "true");
  await expect(dialog(page).getByRole("textbox", { name: "Evidence", exact: true })).toHaveValue("Explicit browser-authored identifier mapping");
  expect((await request.delete(`/api/joins/${join.id}`)).ok()).toBeTruthy();
  const retry = page.waitForResponse((r) => r.url().endsWith("/api/joins") && r.request().method() === "POST");
  await dialog(page).getByRole("button", { name: "Create relation", exact: true }).click();
  expect((await retry).ok()).toBeTruthy();
  await expect(dialog(page)).toBeHidden();
});

test("paths have independent bounded parameters and navigate to a real target", async ({ page }) => {
  await page.goto(url("paths"));
  await expect(page.getByRole("textbox", { name: "At most hops", exact: true })).toHaveCount(0);
  await page.getByRole("button", { name: "Explore paths", exact: true }).click();
  const paths = page.getByRole("region", { name: "Join paths", exact: true });
  await expect(paths).toContainText("Hop arrows below show traversal");
  await expect(paths).toContainText("not the whole graph");
  const hops = paths.getByRole("textbox", { name: "At most hops", exact: true });
  await hops.fill("");
  await expect(paths.getByRole("button", { name: "Explore paths", exact: true })).toBeDisabled();
  await hops.fill("1");
  const response = page.waitForResponse((r) => r.url().includes("/api/joins/path?") && r.url().includes("max_hops=1"));
  await paths.getByRole("button", { name: "Explore paths", exact: true }).click();
  expect((await response).ok()).toBeTruthy();
  await paths.getByRole("link", { name: "Open target object", exact: true }).first().click();
  await expect(page).toHaveURL(new RegExp(encodeURIComponent(objectId("paths", remoteName))));
  await expect(page.getByRole("heading", { level: 1 })).toContainText(remoteName);
});

for (const [locale, messages, prefix] of [["en-US", en, "en"], ["zh-CN", zh, "zh"]] as const) {
  for (const scheme of ["light", "dark"] as const) {
    test(`long endpoints and dialog are usable at narrow short size in ${locale} ${scheme}`, async ({ page, request, baseURL }) => {
      const caseName = `${prefix}-${scheme}`;
      await seedJoin(request, caseName, true);
      await page.context().addCookies([{ name: "refraq.locale", value: locale, url: baseURL! }]);
      await page.addInitScript((value) => localStorage.setItem("mantine-color-scheme-value", value), scheme);
      await page.goto(url(caseName));
      await page.getByRole("button", { name: /^(Language|\u8bed\u8a00)$/ }).click();
      const language = page.getByRole("menuitem", { name: locale === "zh-CN" ? "\u4e2d\u6587" : "English", exact: true });
      if (await language.isEnabled()) await language.click();
      else await page.keyboard.press("Escape");
      await page.goto(url(caseName));
      await page.setViewportSize({ width: 390, height: 520 });
      await expect(page.locator("html")).toHaveAttribute("data-mantine-color-scheme", scheme);
      await expect(page.getByRole("button", { name: messages["catalog.joins.add"], exact: true }).first()).toBeVisible();
      expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth + 1)).toBe(true);
      await page.screenshot({ path: test.info().outputPath("relations-list.png"), fullPage: true });
      await page.getByRole("button", { name: messages["catalog.joins.add"], exact: true }).first().click();
      const form = page.getByRole("region", { name: messages["catalog.joins.add"], exact: true });
      await expect(form.getByRole("combobox", { name: messages["catalog.joins.direction"], exact: true })).toBeFocused();
      const cancel = form.getByRole("button", { name: messages["common.cancel"], exact: true });
      await cancel.scrollIntoViewIfNeeded();
      const box = await cancel.boundingBox();
      expect(box).not.toBeNull();
      expect(box!.y).toBeGreaterThanOrEqual(0);
      expect(box!.y + box!.height).toBeLessThanOrEqual(520);
      await page.screenshot({ path: test.info().outputPath("relations-dialog.png"), fullPage: true });
      await expectAccessible(page).catch((error: Error) => expect.soft(false, error.message).toBe(true));
      await cancel.focus();
      await page.keyboard.press("Enter");
      await expect(form).toBeHidden();
      await page.locator("label").filter({ hasText: messages["catalog.joins.graph.index"] }).click();
      const remote = page.getByRole("link", { name: `${remoteName}.alternate_id`, exact: true });
      await remote.scrollIntoViewIfNeeded();
      await expect.soft(remote).toBeInViewport({ timeout: 2000 });
      await remote.focus();
      await page.keyboard.press("Enter");
      await expect(page).toHaveURL(/obj%2Fpostgresql%2Frelations-/);
      await expect(page.getByRole("heading", { level: 1 })).toContainText(remoteName);
      await expectAccessible(page);
    });
  }
}
