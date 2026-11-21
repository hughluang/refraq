import { expect, test } from "@playwright/test";
import path from "node:path";
import { createRole, createUser, stamp } from "./api";
import { signIn } from "./auth";
import en from "../src/locales/en-US/common.json";
import zh from "../src/locales/zh-CN/common.json";

for (const [locale, t] of [["en-US", en], ["zh-CN", zh]] as const) {
  test(`verify an order through a published Channel in ${locale}`, async ({ page, request }, info) => {
    test.setTimeout(180_000);
    await page.setViewportSize({ width: 1440, height: 1000 });
    const capture = (stage: string) => page.screenshot({
      path: path.join(process.env.CDC_SCREENSHOTS ?? info.outputDir, `${locale}-${stage}.png`),
    });
    const key = stamp();
    const role = await createRole(request, { key: `sales_${key}`, name: "Sales analyst", permissions: [
      "console:access", "channel:read", "channel:write", "mirror:read", "metadata:read", "sources:read", "sources:data_read",
    ] });
    const password = `Test-analyst-${key}`;
    const actor = await createUser(request, { account: `sales_${key}`, display_name: "Sales analyst", password, role_id: role.id });
    const source = `src_sales-${locale.slice(0, 2)}`;
    const grant = await request.post(`/api/sources/${source}/memberships`, { data: { subject: { type: "user", id: actor.id }, level: "viewer" } });
    expect(grant.ok(), await grant.text()).toBeTruthy();
    await page.context().clearCookies();
    await signIn(page, actor.account, password);
    // Source Mirrors is global. Each locale starts with an independent empty registry view.
    await page.route("**/api/mirrors?*", route => route.fulfill({ json: { items: [], total: 0, offset: 0, limit: 50 } }));
    await page.goto("/console/mirrors");
    if (locale === "zh-CN") {
      await page.getByRole("button", { name: "Language", exact: true }).click();
      await page.getByRole("menuitem", { name: "\u4e2d\u6587", exact: true }).click();
    }
    const choose = page.getByRole("link", { name: t["catalog.chooseSyncTable"] });
    await expect(choose).toBeVisible();
    await capture("01-operations");
    await choose.click();
    await page.getByRole("link", { name: "orders", exact: true }).click();
    const setup = page.getByRole("link", { name: t["channels.create.setupTable"] });
    await expect(setup).toBeVisible();
    await capture("02-catalog");
    await setup.click();
    await expect(page.getByText("Sales / public.orders", { exact: true })).toBeVisible();
    await page.getByRole("textbox", { name: t["channels.fields.name"] }).fill("Sales order amounts");
    await capture("03-create");
    await page.getByRole("button", { name: t["channels.create.submit"], exact: true }).click();
    const publish = page.getByRole("button", { name: t["channels.actions.publish"], exact: true });
    await expect(publish).toBeVisible({ timeout: 60_000 });
    await expect(page.getByText(`${t["channels.draft.table"]} · Sales / public.orders`)).toBeVisible();
    await expect(page.getByText(t["channels.seed.manual"], { exact: true }).first()).toBeVisible();
    await capture("04-draft");
    await publish.click();
    const review = page.getByRole("dialog");
    await expect(review.getByText("Sales / public.orders")).toBeVisible();
    await expect(review.getByText(t["channels.tableReview.first_open"])).toBeVisible();
    await capture("05-review");
    await review.getByRole("button", { name: t["channels.publish.confirm"], exact: true }).click();
    const follow = page.getByRole("link", { name: t["channels.tableReview.follow"] });
    await expect(follow).toBeVisible();
    await page.reload();
    await expect(follow).toBeVisible();
    await capture("06-published");
    await follow.click();
    await expect(page.getByText(t["mirrors.event.first"], { exact: false }).first()).toBeVisible();
    await capture("07-request");
    const mirror = new URL(page.url()).pathname.split("/").pop();
    const copy = (amount: string) => request.post(`/api/e2e/sales/${mirror}/copy`, { params: { amount } });
    const before = await copy("24.60");
    expect(before.ok(), await before.text()).toBeTruthy();
    await page.getByRole("button", { name: t["common.refresh"], exact: true }).click();
    const run = t["channels.verify.run"];
    await expect(page.getByText(t["mirrors.event.published"], { exact: true })).toBeVisible();
    await expect(page.getByRole("link", { name: run, exact: true })).toBeVisible();
    await capture("08-copy");
    await page.getByRole("link", { name: run, exact: true }).click();
    const confirm = page.getByRole("dialog").getByRole("button", { name: t["channels.run.confirm"], exact: true });
    await confirm.click();
    const order = page.getByRole("row").filter({ hasText: "ORD-104" });
    await expect(page.getByText(t["channels.verify.policy"])).toBeVisible();
    await expect(order).toHaveCount(0);

    const channelId = new URL(page.url()).pathname.split("/")[3];
    const draftUrl = `/api/channels/${channelId}/draft`;
    const draftResponse = await request.get(draftUrl);
    expect(draftResponse.ok(), await draftResponse.text()).toBeTruthy();
    const draft = await draftResponse.json();
    const read = draft.graph.nodes.find((node: { type: string }) => node.type === "read.mirror");
    expect(read.config.freshness_policy).toBe("fail");
    read.config.freshness_policy = "continue";
    const saved = await request.put(draftUrl, { data: { base_revision: draft.draft_revision, graph: draft.graph } });
    expect(saved.ok(), await saved.text()).toBeTruthy();
    const edit = `/console/channels/${channelId}/edit`;
    await page.goto(edit);
    await publish.click();
    await review.getByRole("button", { name: t["channels.publish.confirm"], exact: true }).click();
    await expect(follow).toBeVisible();
    await page.getByRole("button", { name: run, exact: true }).click();
    await confirm.click();
    await expect(order).toContainText("24.60");
    await expect(page.getByText(t["channels.verify.unknown"])).toBeVisible();
    const firstUrl = page.url();
    const first = new URL(firstUrl).pathname.split("/").pop()!;
    await expect(page.getByText(first, { exact: true })).toBeVisible();
    await capture("09-before");
    const after = await copy("26.75");
    expect(after.ok(), await after.text()).toBeTruthy();
    await page.getByRole("link", { name: t["channels.runDetail.back"], exact: true }).click();
    await expect(page.getByRole("dialog")).toBeVisible();
    await page.keyboard.press("Escape");
    await expect(page.getByRole("dialog")).toBeHidden();
    await page.getByRole("button", { name: run, exact: true }).click();
    await confirm.click();
    await expect(order).toContainText("26.75");
    const second = new URL(page.url()).pathname.split("/").pop()!;
    expect(second).not.toEqual(first);
    await expect(page.getByText(second, { exact: true })).toBeVisible();
    await capture("10-after");
    await page.goto(firstUrl);
    await expect(order).toContainText("24.60");
    await capture("11-reopened");
    console.info(`${locale}: ORD-104 ${first}=24.60; ${second}=26.75; reopened ${first}=24.60`);
  });
}
