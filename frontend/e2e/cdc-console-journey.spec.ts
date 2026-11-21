import { expect, test, type Page } from "@playwright/test";

import en from "../src/locales/en-US/common.json";
import zh from "../src/locales/zh-CN/common.json";
import { createRole, createUser, stamp } from "./api";
import { signIn } from "./auth";

test("Channel authoring offers Entity changes and omits Mirror inputs", async ({ page, request }) => {
  const response = await request.post("/api/channels", { data: { name: `Entity changes ${stamp()}` } });
  expect(response.ok(), await response.text()).toBeTruthy();
  const { channel } = await response.json();
  await page.goto(`/console/channels/${channel.id}/edit`);
  const toolbar = page.getByRole("toolbar", { name: en["channels.canvas.toolbar"] });
  await toolbar.getByRole("button", { name: en["channels.canvas.add"], exact: true }).click();

  const palette = page.getByRole("listbox", { name: en["channels.canvas.palette"] });
  const changes = palette.getByRole("option").filter({ hasText: en["channelNodeTypes.read.changes.label"] });
  await expect(changes).toBeVisible();
  await expect(palette.locator("#channel-picker-option-read-mirror")).toHaveCount(0);
  await changes.click();

  const node = page.locator(".react-flow__node-channel").filter({ hasText: en["channelNodeTypes.read.changes.label"] });
  await node.dblclick();
  await expect(page.getByRole("button", { name: en["channels.config.fields.read.changes.entity_id"], exact: true })).toBeVisible();
  await expect(page.getByText("Change stream", { exact: true })).toHaveCount(0);
});

for (const [locale, t] of [["en-US", en], ["zh-CN", zh]] as const) {
  test(`enable an Orders mirror from Catalog in ${locale}`, async ({ page, browser, request, baseURL }) => {
    const prefix = `sales-${locale.slice(0, 2)}`;
    const objectId = `${prefix}-orders`;
    const catalogUrl = `/console/catalog/${objectId}`;
    const enableUrl = `/api/objects/${objectId}/mirror`;
    const suffix = stamp();
    const password = `Catalog-test-${suffix}`;

    async function actor(kind: string, permissions: string[]) {
      const key = `${kind}_${suffix}`;
      const role = await createRole(request, {
        key, name: kind, permissions: ["console:access", "metadata:read", "sources:read", ...permissions],
      });
      const user = await createUser(request, { account: key, display_name: kind, password, role_id: role.id });
      const grant = await request.post(`/api/sources/src_${prefix}/memberships`, {
        data: { subject: { type: "user", id: user.id }, level: "viewer" },
      });
      expect(grant.ok(), await grant.text()).toBeTruthy();
      return user.account;
    }

    async function openCatalog(page: Page) {
      if (locale === "zh-CN") {
        await page.getByRole("button", { name: "Language", exact: true }).click();
        await page.getByRole("menuitem", { name: "\u4e2d\u6587", exact: true }).click();
      }
      await page.goto(catalogUrl);
      await expect(page.getByRole("heading", { name: "public.orders", exact: true })).toBeVisible();
    }

    const catalogReader = await actor("catalog_reader", []);
    const operator = await actor("mirror_operator", ["mirror:read", "mirror:write"]);
    const readerContext = await browser.newContext({ baseURL, storageState: { cookies: [], origins: [] } });
    try {
      const reader = await readerContext.newPage();
      await signIn(reader, catalogReader, password);
      await openCatalog(reader);
      await expect(reader.getByRole("button", { name: t["catalog.mirror.enable"], exact: true })).toHaveCount(0);
      expect((await reader.request.post(enableUrl)).status()).toBe(403);

      await page.context().clearCookies();
      await signIn(page, operator, password);
      await openCatalog(page);

      const enable = page.getByRole("button", { name: t["catalog.mirror.enable"], exact: true });
      await expect(enable).toBeVisible();
      const acceptance = page.waitForResponse(response =>
        new URL(response.url()).pathname === enableUrl && response.request().method() === "POST",
      );
      await enable.click();
      const accepted = await acceptance;
      expect(accepted.status(), await accepted.text()).toBe(202);
      const { mirror, operation_id } = await accepted.json();
      await expect(page.getByText(t["catalog.mirror.accepted"], { exact: true })).toBeVisible();
      const repeated = await page.request.post(enableUrl);
      expect(repeated.status(), await repeated.text()).toBe(202);
      expect(await repeated.json()).toMatchObject({ mirror: { id: mirror.id }, operation_id });

      const follow = page.getByRole("link", { name: t["catalog.mirror.view"], exact: true });
      await page.reload();
      await expect(follow).toHaveAttribute("href", `/console/mirrors/${mirror.id}`);
      await reader.reload();
      await expect(reader.getByRole("heading", { name: "public.orders", exact: true })).toBeVisible();
      await expect(reader.getByRole("link", { name: t["catalog.mirror.view"], exact: true })).toHaveCount(0);
      expect((await reader.request.get(`/api/mirrors/${mirror.id}`)).status()).toBe(403);

      await follow.click();
      await expect(page.getByText(t["mirrors.event.first"])).toBeVisible();
      const published = page.getByText(t["mirrors.event.published"], { exact: true });
      await expect(published).toHaveCount(0);
      await expect(page.getByText(t["mirrors.confirmCapture"], { exact: true })).toBeVisible();

      const detailUrl = `**/api/mirrors/${mirror.id}`;
      const refresh = page.getByRole("button", { name: t["common.refresh"], exact: true });
      // Stand in for a published pointer delivered by the deployment. The real API supplies intent.
      await page.route(detailUrl, async route => {
        const response = await route.fetch();
        const body = await response.json();
        await route.fulfill({ response, json: {
          ...body, mirror: { ...body.mirror, published_generation_id: "e2e-published-generation" },
        } });
      });
      await refresh.click();
      await expect(published).toBeVisible();
      await expect(page.getByText(t["mirrors.freshnessUnknown"], { exact: true })).toBeVisible();
      await page.unroute(detailUrl);

      await page.getByRole("button", { name: t["mirrors.disable"], exact: true }).click();
      await page.getByRole("dialog").getByRole("button", { name: t["common.confirm"], exact: true }).click();
      await expect(page.getByText(t["mirrors.status.disable_pending"], { exact: true })).toBeVisible();
      await page.reload();
      await expect(page.getByText(t["mirrors.status.disable_pending"], { exact: true })).toBeVisible();
      await expect(page.getByText(t["mirrors.event.disableRequested"], { exact: true })).toBeVisible();
      await expect(page.getByText(t["mirrors.event.stopConfirmed"])).toHaveCount(0);
      await expect(page.getByRole("button", { name: t["mirrors.enable"], exact: true })).toBeDisabled();
    } finally {
      await readerContext.close();
    }
  });
}
