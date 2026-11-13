import { expect, test } from "@playwright/test";
import { stamp } from "./api";
import en from "../src/locales/en-US/common.json";
import zh from "../src/locales/zh-CN/common.json";

for (const [locale, messages] of [["en-US", en], ["zh-CN", zh]] as const) {
test(`positionless auto diagrams preserve nested and wired-error geometry in ${locale}`, async ({ page, request }) => {
  const response = await request.post("/api/channels", { data: { name: `Layout ${stamp()}` } });
  expect(response.ok(), await response.text()).toBeTruthy();
  const { channel } = await response.json();
  const node = (id: string, type: string, parent?: string) => ({ id, ref: id, type, name: id, config: {}, on_error: "stop", retry: null, ...(parent ? { parent } : {}) });
  const nodes = [node("nd_outer", "volume.for"), node("nd_inner", "volume.for", "nd_outer"), node("nd_branch", "transform.if", "nd_inner"), node("nd_leaf", "transform.code", "nd_inner"), node("nd_after", "read.sql"), node("nd_error", "transform.code")];
  const edge = (id: string, source: string, port: string, target: string) => ({ id, source: { node_id: source, port }, target: { node_id: target, port: "main" } });
  const saved = await request.put(`/api/channels/${channel.id}/draft`, { data: { base_revision: channel.draft_revision, graph: { layout: { mode: "auto" }, nodes, edges: [edge("ed_outer", "nd_outer", "each", "nd_inner"), edge("ed_inner", "nd_inner", "each", "nd_branch"), edge("ed_branch", "nd_branch", "true", "nd_leaf"), edge("ed_after", "nd_outer", "done", "nd_after"), edge("ed_error", "nd_after", "error", "nd_error")], settings: { run_timeout_sec: null, error_channel_id: null } } } });
  expect(saved.ok(), await saved.text()).toBeTruthy();
  await page.setViewportSize({ width: 1440, height: 1000 });
  await page.goto(`/console/channels/${channel.id}/edit`);
  if (locale === "zh-CN") {
    await page.getByRole("button", { name: /^(Language|\u8bed\u8a00)$/, exact: true }).click();
    await page.getByRole("menuitem", { name: "\u4e2d\u6587", exact: true }).click();
  }
  const arrange = page.getByRole("button", { name: messages["channels.canvas.arrange"], exact: true });
  await expect(arrange).toBeEnabled();
  const geometry = () => page.locator(".react-flow__node-channel").evaluateAll((elements) => elements.map((element) => {
    const rect = element.getBoundingClientRect();
    return { id: element.getAttribute("data-id"), x: rect.x, y: rect.y, width: rect.width, height: rect.height };
  }));
  await expect.poll(async () => {
    const boxes = await geometry();
    const byId = new Map(boxes.map((box) => [box.id, box]));
    if (boxes.length !== nodes.length) return false;
    for (const item of nodes) {
      const box = byId.get(item.id)!;
      if (![box.x, box.y, box.width, box.height].every(Number.isFinite) || box.width <= 0 || box.height <= 0) return false;
      if (item.parent) {
        const parent = byId.get(item.parent)!;
        if (box.x < parent.x || box.y <= parent.y + 10 || box.x + box.width > parent.x + parent.width + 1 || box.y + box.height > parent.y + parent.height + 1) return false;
      }
      for (const other of nodes.filter((candidate) => candidate.id !== item.id && candidate.parent === item.parent)) {
        const sibling = byId.get(other.id)!;
        if (box.x < sibling.x + sibling.width - 1 && sibling.x < box.x + box.width - 1 && box.y < sibling.y + sibling.height - 1 && sibling.y < box.y + box.height - 1) return false;
      }
    }
    return true;
  }).toBe(true);
  const errorHandle = page.locator('[data-id="nd_after"] .react-flow__handle[data-handleid="error"]');
  await expect(errorHandle).toBeVisible();
  expect(await errorHandle.evaluate((handle) => {
    const port = handle.getBoundingClientRect();
    const card = handle.closest(".react-flow__node")!.getBoundingClientRect();
    return port.y >= card.y && port.bottom <= card.bottom;
  })).toBe(true);
  await page.screenshot({ path: test.info().outputPath("nested-auto-layout.png"), fullPage: true });
  await arrange.click();
  await expect(arrange).toBeEnabled();
  await page.getByRole("button", { name: messages["actions.save"], exact: true }).click();
  await expect.poll(async () => {
    const result = await request.get(`/api/channels/${channel.id}/draft`);
    return (await result.json()).graph.layout.mode;
  }).toBe("manual");
  const stored = await (await request.get(`/api/channels/${channel.id}/draft`)).json();
  expect(stored.graph.nodes.map((item: { execution_order: number }) => item.execution_order)).toEqual([0, 1, 2, 3, 4, 5]);
});
}
