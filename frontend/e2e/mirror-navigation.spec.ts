import { expect, test } from "@playwright/test";

import { createRole, createUser, stamp } from "./api";
import { signIn } from "./auth";

test("a Mirror reader restores the paged Catalog drawer and follows the Source snapshot slot", async ({ page }) => {
  const source = { id: "source-1", key: "sales", name: "Sales", engine: "postgresql" };
  const holder = { mirror_id: "m1", qualified_table: "public.orders_01" };
  const tables = Array.from({ length: 20 }, (_, index) => {
    const number = index + 1;
    return {
      object_id: `obj${number}`, qualified_table: `public.orders_${String(number).padStart(2, "0")}`,
      source_id: source.id, source_key: source.key, source_name: source.name,
      storage_destination: "source_mirror", source_size_bytes: 8192, estimated_rows: 50,
      mirror: { enabled: number !== 19, can_enable: false, can_disable: false, mirror_id: `m${number}` },
      snapshot_holder: number === 20 ? holder : null,
    };
  });
  await page.route("**/api/auth/me", async route => {
    const response = await route.fetch();
    const body = await response.json();
    await route.fulfill({ response, json: { ...body, user: { ...body.user,
      locale: "en-US", permissions: ["console:access", "metadata:read", "mirror:read"] } } });
  });
  await page.route("**/api/catalog/sources?**", route => route.fulfill({ json: { items: [source], total: 1, offset: 0, limit: 20 } }));
  await page.route("**/api/catalog/mirror-tables?**", route => {
    const query = new URL(route.request().url()).searchParams;
    const offset = Number(query.get("offset")), limit = Number(query.get("limit"));
    const matches = tables.filter(row => (!query.has("object_id") || row.object_id === query.get("object_id"))
      && (!query.has("source_id") || row.source_id === query.get("source_id"))
      && row.qualified_table.toLowerCase().includes((query.get("q") ?? "").toLowerCase()));
    return route.fulfill({ json: { items: matches.slice(offset, offset + limit), total: matches.length, limit, offset } });
  });
  await page.route("**/api/sources/source-1/objects?**", route => route.fulfill({ json: { items: [], total: 0, limit: 100, offset: 0 } }));
  await page.route("**/api/mirrors/m*", route => {
    const id = new URL(route.request().url()).pathname.split("/").pop();
    const table = tables.find(row => row.mirror.mirror_id === id)!;
    return route.fulfill({ json: { can_enable: false, mirror: {
      ...table, id, enabled: table.mirror.enabled, status: table.mirror.enabled ? "waiting" : "disabled",
      published_generation_id: null, capture_generation: null, history_epoch: null, progress: null,
      control: { control_revision: 1, applied_revision: null, stop_ack: null }, readiness: [], operations: [],
      profile: {}, fault: null, snapshot_slot_holder: table.snapshot_holder,
    } } });
  });
  await page.setViewportSize({ width: 1000, height: 530 });
  await page.goto("/console/catalog?source=source-1");
  await page.getByRole("button", { name: "Choose table" }).click();
  const drawer = page.getByRole("dialog");
  const search = drawer.getByRole("textbox", { name: "Qualified table name" });
  const secondPage = page.waitForRequest(request => {
    const url = new URL(request.url());
    return url.pathname.endsWith("/catalog/mirror-tables") && url.searchParams.get("q") === "public.orders"
      && url.searchParams.get("source_id") === source.id && url.searchParams.get("limit") === "10"
      && url.searchParams.get("offset") === "10";
  });
  await search.fill("public.orders");
  await expect(page).toHaveURL(/tableQuery=public.orders/);
  await drawer.getByRole("button", { name: "2", exact: true }).click();
  await secondPage;
  await expect(page).toHaveURL(/tablePage=2/);
  const row = drawer.getByRole("button", { name: "public.orders_20", exact: true });
  await row.scrollIntoViewIfNeeded();
  const scroll = await drawer.evaluate(node => node.scrollTop);
  await row.click();
  await expect(drawer.getByRole("link", { name: holder.qualified_table })).toBeVisible();
  const follow = drawer.getByRole("link", { name: "View mirror" });
  await follow.click();
  await expect(page).toHaveURL(/\/console\/mirrors\/m20\?/);
  await expect(drawer).toHaveCount(0);
  const holderLink = page.getByRole("link", { name: holder.qualified_table });
  await holderLink.click();
  await expect(page).toHaveURL(/\/console\/mirrors\/m1\?/);
  await page.getByRole("link", { name: "Back to waiting table" }).click();
  await expect(holderLink).toBeFocused();
  await page.getByRole("link", { name: "Back to table" }).click();
  await expect(follow).toBeFocused();
  await drawer.getByRole("button", { name: "Back to tables" }).click();
  await expect(row).toBeFocused();
  await expect(search).toHaveValue("public.orders");
  expect(await drawer.evaluate(node => node.scrollTop)).toBe(scroll);
  await page.goBack();
  await expect(follow).toBeVisible();
  await page.goForward();
  await expect(row).toBeFocused();
  await drawer.getByRole("button", { name: "public.orders_19", exact: true }).click();
  await expect(drawer.getByRole("switch")).toBeDisabled();
  await expect(drawer.getByRole("switch")).not.toBeChecked();
  await follow.click();
  await expect(page.getByRole("heading", { name: "public.orders_19" })).toBeVisible();
  await expect(page.getByRole("switch")).toBeDisabled();
});

test("a Catalog writer can enable a table on mobile and sees the accepted Open", async ({ page, request }) => {
  const suffix = stamp();
  const account = `mirror_writer_${suffix}`;
  const password = `Catalog-test-${suffix}`;
  const role = await createRole(request, {
    key: account, name: account, permissions: ["console:access", "metadata:read", "mirror:write"],
  });
  const user = await createUser(request, { account, display_name: account, password, role_id: role.id });
  const sourceId = "src_relations-author";
  const grant = await request.post(`/api/sources/${sourceId}/memberships`, {
    data: { subject: { type: "user", id: user.id }, level: "viewer" },
  });
  expect(grant.ok(), await grant.text()).toBeTruthy();

  await page.setViewportSize({ width: 390, height: 844 });
  await page.context().clearCookies();
  await signIn(page, account, password);
  await page.goto(`/console/catalog?source=${sourceId}`);
  await page.getByRole("button", { name: "Choose table" }).click();
  const drawer = page.getByRole("dialog");
  await drawer.getByRole("textbox", { name: "Qualified table name" }).fill("PUBLIC.ORDERS");
  await expect(drawer.getByRole("button", { name: "public.orders", exact: true })).toBeVisible();
  await drawer.getByRole("button", { name: "public.orders", exact: true }).click();
  const receipt = page.waitForResponse(response =>
    response.url().endsWith("/objects/relations-author-orders/mirror") && response.request().method() === "PUT",
  );
  await drawer.getByRole("switch", { name: "Mirror synchronization" }).click();
  const response = await receipt;
  expect(response.ok(), await response.text()).toBeTruthy();
  const accepted = await response.json();
  expect(accepted.mirror.mirror_id).toBeNull();
  await expect(drawer.getByText(accepted.operation_id, { exact: true })).toBeVisible();
  await expect(drawer.getByRole("switch")).toBeChecked();
  await expect(drawer.getByRole("link", { name: "View mirror" })).toHaveCount(0);
  expect((await page.request.get("/api/mirrors")).status()).toBe(403);
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);
});

test("pending publication survives a failed poll and hides evidence when access changes", async ({ page }) => {
  const id = "m-poll";
  const table = "public.pending";
  let stage: "window" | "offline" | "catchup" | "revoked" = "window";
  await page.route(`**/api/mirrors/${id}`, route => {
    if (stage === "offline" || stage === "revoked") {
      return route.fulfill({
        status: stage === "offline" ? 503 : 403,
        json: { code: stage === "offline" ? "MIRROR_READ_UNAVAILABLE" : "AUTH_FORBIDDEN" },
      });
    }
    const observed = "2026-11-23T07:14:00Z";
    const readiness = [{ key: "capture_admission", result: "pass", observed_at: observed, action: "" }];
    if (stage === "window") readiness.push({ key: "snapshot_window_closed", result: "fail", observed_at: observed, action: "" });
    return route.fulfill({ json: { can_enable: false, mirror: {
      id, qualified_table: table, source_id: "sales", source_name: "Sales", storage_destination: "source_mirror",
      enabled: true, status: stage === "window" ? "waiting" : "catching_up", readiness, profile: {}, fault: null,
      published_generation_id: null, history_epoch: null, capture_generation: "capture-1",
      progress: stage === "window" ? null : { stage: "catching_up", generation_id: "g1", notification_offset: 4,
        observed_at: observed, scanned_bytes: 8192, byte_notification_offset: 3, bytes_observed_at: observed,
        scan_percent: 100, scan_complete: true },
      operations: [{ id: "open-1", kind: "open", state: "pending", control_revision: 1, requested_at: observed }],
      control: { control_revision: 1, applied_revision: 1, stop_ack: null },
    } } });
  });
  await page.goto(`/console/mirrors/${id}`);
  const heading = page.getByRole("heading", { name: table, exact: true });
  await expect(heading).toBeVisible();
  await expect(page.getByText("Wait for the Source snapshot window to open.", { exact: true }).first()).toBeVisible();
  await expect(page.getByText("No published copy", { exact: true })).toBeVisible();
  stage = "offline";
  await page.waitForResponse(r => r.url().endsWith(`/mirrors/${id}`) && r.status() === 503);
  await expect(heading).toBeVisible();
  await expect(page.getByText("Awaiting verified publication", { exact: true }).first()).toBeVisible();
  stage = "catchup";
  await expect(page.getByText("100%", { exact: true }).first()).toBeVisible();
  await expect(page.getByText("No published copy", { exact: true })).toBeVisible();
  stage = "revoked";
  await expect(heading).toHaveCount(0);
  await expect(page.getByText("100%", { exact: true })).toHaveCount(0);
});
