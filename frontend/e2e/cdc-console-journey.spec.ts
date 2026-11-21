import { expect, test } from "@playwright/test";

import en from "../src/locales/en-US/common.json";
import { stamp } from "./api";

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
