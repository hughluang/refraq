import { expect, test } from "@playwright/test";
import zh from "../src/locales/zh-CN/common.json";

test("bounded route spotlights retain stored LEFT direction, exact ports and read-only hop details", async ({ page, request }) => {
  const object = "relations-edit-orders";
  const remote = "relations-edit-customer_accounts_with_a_deliberately_long_catalog_object_name";
  const created = await request.post("/api/joins", { data: { from_column_id: `${remote}-alternate_id`, to_column_id: `${object}-id`, evidence: "Reverse traversal evidence", join_kind: "LEFT", join_expression: "remote.alternate_id = orders.id" } });
  expect(created.ok()).toBe(true);
  const saved = (await created.json()).join;
  await page.setViewportSize({ width: 1500, height: 950 });
  await page.goto(`/console/catalog/${object}?tab=joins`);
  await page.getByRole("button", { name: "Explore paths", exact: true }).click();
  const paths = page.getByRole("region", { name: "Join paths", exact: true });
  await expect(paths.getByLabel("At most hops")).toBeFocused();
  await expect(paths).toContainText("Returned count is not the total reachable count");
  await expect(paths).toContainText("Evidence: Reverse traversal evidence");
  await expect(paths).toContainText("Reported join kind (stored meaning): LEFT");
  await expect(paths).toContainText("remote.alternate_id = orders.id");
  await expect(paths.getByRole("button", { name: "Edit", exact: true })).toHaveCount(0);
  const graph = paths.getByRole("region", { name: "Relation graph", exact: true });
  await expect(graph.locator(".react-flow__edge")).toHaveCount(1);
  await expect(graph.locator(".react-flow__edge")).toHaveAttribute("aria-label", "1 · Stored direction · LEFT");
  expect(await graph.locator(".react-flow__edge-path").evaluate((element, ids) => {
    const path = element as SVGPathElement;
    return [0, path.getTotalLength()].every((distance, index) => {
      const point = path.getPointAtLength(distance).matrixTransform(path.getScreenCTM()!);
      const prefix = index === 0 ? `from:${ids.remote}:` : `to:${ids.local}:`;
      return [...document.querySelectorAll(".react-flow__handle")].some((handle) => {
        const box = handle.getBoundingClientRect();
        return handle.getAttribute("data-handleid")?.startsWith(prefix) && Math.hypot(point.x - box.x - box.width / 2, point.y - box.y - box.height / 2) < 5;
      });
    });
  }, { remote: `${remote}-alternate_id`, local: `${object}-id` })).toBe(true);
  await page.screenshot({ path: test.info().outputPath("relations-path-spotlight.png") });
  await page.setViewportSize({ width: 390, height: 650 });
  await paths.getByRole("button", { name: "Join paths", exact: true }).click();
  await expect(paths.getByRole("region", { name: "Returned routes" })).toBeVisible();
  await expect(paths).toContainText("Evidence: Reverse traversal evidence");
  await page.screenshot({ path: test.info().outputPath("relations-path-narrow.png"), fullPage: true });
  const exit = paths.getByRole("button", { name: "Back to neighborhood" });
  await exit.focus();
  await page.keyboard.press("Enter");
  await expect(paths).toHaveCount(0);
  await expect(page.getByRole("button", { name: "Explore paths", exact: true })).toBeFocused();
  expect((await request.delete(`/api/joins/${saved.id}`)).ok()).toBe(true);
});

test("path bounds and read-only route details remain usable in Chinese dark mode", async ({ page, baseURL }) => {
  await page.context().addCookies([{ name: "refraq.locale", value: "zh-CN", url: baseURL! }]);
  await page.addInitScript(() => localStorage.setItem("mantine-color-scheme-value", "dark"));
  await page.setViewportSize({ width: 640, height: 740 });
  await page.goto("/console/catalog/relations-zh-dark-orders?tab=joins");
  await page.getByRole("button", { name: /^(Language|\u8bed\u8a00)$/ }).click();
  const language = page.getByRole("menuitem", { name: "\u4e2d\u6587", exact: true });
  if (await language.isEnabled()) await language.click();
  else await page.keyboard.press("Escape");
  await page.goto("/console/catalog/relations-zh-dark-orders?tab=joins");
  await page.getByRole("button", { name: zh["catalog.joins.path.explore"], exact: true }).click();
  const paths = page.getByRole("region", { name: zh["catalog.joins.path.title"], exact: true });
  await expect(paths.getByLabel(zh["catalog.joins.path.maxHops"])).toBeFocused();
  await expect(paths).toContainText(zh["catalog.joins.path.scope"]);
  await expect(page.locator("html")).toHaveAttribute("data-mantine-color-scheme", "dark");
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth + 1)).toBe(true);
  await page.screenshot({ path: test.info().outputPath("relations-path-zh-dark.png") });
  await page.getByRole("button", { name: /^(Language|\u8bed\u8a00)$/ }).click();
  await page.getByRole("menuitem", { name: "English", exact: true }).click();
  await expect(page.getByRole("button", { name: "Explore paths", exact: true })).toBeVisible();
});

test("dense multi-remote neighborhoods keep measured cards separate and support exact-column inspection", async ({ page, request }) => {
  const object = "relations-dense-orders";
  for (let remote = 0; remote < 3; remote += 1) {
    const target = `relations-dense-remote_${remote}_with_a_deliberately_long_catalog_object_name`;
    for (const column of ["id", "alternate_id", "foreign_id"]) {
      const response = await request.post("/api/joins", { data: { from_column_id: `${object}-${column}`, to_column_id: `${target}-${column}`, evidence: `Dense remote ${remote} ${column}`, join_kind: remote === 1 ? "RIGHT" : "LEFT" } });
      expect(response.ok()).toBe(true);
    }
  }
  await page.setViewportSize({ width: 1500, height: 950 });
  await page.goto(`/console/catalog/${object}?tab=joins`);
  const graph = page.getByRole("region", { name: "Relation graph", exact: true });
  await expect(graph.locator(".react-flow__node")).toHaveCount(5);
  await expect(graph.locator(".react-flow__edge")).toHaveCount(10);
  await expect.poll(() => graph.locator(".react-flow__node").evaluateAll((nodes) => {
    const boxes = nodes.map((node) => node.getBoundingClientRect());
    return boxes.every((a, index) => boxes.slice(index + 1).every((b) => a.right <= b.left || b.right <= a.left || a.bottom <= b.top || b.bottom <= a.top));
  })).toBe(true);
  await expect(page.getByText(/10 loaded of 10 incident relations/)).toBeVisible();
  const desktopInspect = page.getByRole("region", { name: "Relation index", exact: true }).getByRole("button", { name: "Inspect relation", exact: true }).first();
  await desktopInspect.focus();
  await desktopInspect.press("Enter");
  const detail = page.getByRole("region", { name: "Relation details", exact: true });
  await expect(detail).toBeVisible();
  await expect(page.getByRole("dialog")).toHaveCount(0);
  await detail.getByRole("button", { name: "Back to graph and index" }).click();
  await expect(detail).toHaveCount(0);
  await expect(desktopInspect).toBeFocused();
  const current = graph.locator(".react-flow__node").filter({ hasText: "Current object" });
  await current.getByRole("button", { name: /^id/ }).click();
  await expect(graph.getByRole("button", { name: "Clear column focus" })).toBeVisible();
  await expect.poll(() => graph.locator(".react-flow__edge-path").evaluateAll((paths) => paths.filter((path) => getComputedStyle(path).opacity === "0.15").length)).toBe(7);
  await graph.getByRole("button", { name: "Clear column focus" }).click();
  await page.screenshot({ path: test.info().outputPath("relations-dense-multiple-remotes.png") });
  await page.setViewportSize({ width: 390, height: 650 });
  await page.locator("label").filter({ hasText: /^Relation index$/ }).click();
  const index = page.getByRole("region", { name: "Relation index", exact: true });
  const inspect = index.getByRole("button", { name: "Inspect relation", exact: true }).last();
  await inspect.focus();
  await page.keyboard.press("Enter");
  await expect(detail).toContainText("Dense remote 2 foreign_id");
  await expect(page.getByRole("dialog")).toHaveCount(0);
  await expect(index).toBeHidden();
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth + 1)).toBe(true);
  await page.screenshot({ path: test.info().outputPath("relations-dense-narrow-inspection.png") });
  await detail.getByRole("button", { name: "Back to graph and index" }).click();
  await expect(index).toBeVisible();
  await expect(graph).toBeHidden();
  await expect(inspect).toBeFocused();
});

test("catalog graph exposes measured column ports, separate directed edges and keyboard inspection", async ({ page, request }) => {
  const object = "relations-paths-orders";
  const remote = "relations-paths-customer_accounts_with_a_deliberately_long_catalog_object_name";
  const expectedPorts: Record<string, { from: string; to: string }> = {};
  const initial = await request.get(`/api/objects/${object}/joins`);
  for (const join of (await initial.json()).items) expectedPorts[join.id] = { from: join.from_column_id, to: join.to_column_id };
  for (const [from, to] of [[`${object}-id`, `${remote}-alternate_id`], [`${remote}-alternate_id`, `${object}-id`], [`${object}-alternate_id`, `${object}-id`]]) {
    const response = await request.post("/api/joins", { data: { from_column_id: from, to_column_id: to, evidence: "Graph browser inspection", join_kind: "LEFT" } });
    expect(response.ok()).toBe(true);
    const join = (await response.json()).join;
    expectedPorts[join.id] = { from, to };
  }
  await page.setViewportSize({ width: 1500, height: 950 });
  await page.goto(`/console/catalog/${object}?tab=joins`);
  const graph = page.getByRole("region", { name: "Relation graph", exact: true });
  await expect(graph.locator(".react-flow__node")).toHaveCount(2);
  await expect(graph.locator(".react-flow__edge")).toHaveCount(4);
  await page.getByRole("button", { name: "Fit", exact: true }).click();
  const anchored = await graph.locator(".react-flow__edge").evaluateAll((edges, ports) => edges.every((edge) => {
    const pair = ports[edge.getAttribute("data-id")!]!;
    const path = edge.querySelector<SVGPathElement>(".react-flow__edge-path")!;
    const start = path.getPointAtLength(0);
    const end = path.getPointAtLength(path.getTotalLength());
    const matrix = path.getScreenCTM()!;
    return [start, end].every((point, index) => {
      const screen = new DOMPoint(point.x, point.y).matrixTransform(matrix);
      const prefix = index === 0 ? `from:${pair.from}:` : `to:${pair.to}:`;
      return [...document.querySelectorAll(".react-flow__handle")].filter((handle) => handle.getAttribute("data-handleid")?.startsWith(prefix)).some((handle) => {
        const box = handle.getBoundingClientRect();
        return Math.hypot(screen.x - box.x - box.width / 2, screen.y - box.y - box.height / 2) < 5;
      });
    });
  }), expectedPorts);
  expect(anchored).toBe(true);
  const handles = graph.locator(".react-flow__handle");
  for (const handle of await handles.all()) {
    const bounds = await handle.boundingBox();
    expect(bounds?.width).toBeGreaterThan(0);
    expect(bounds?.height).toBeGreaterThan(0);
  }
  const paths = await graph.locator(".react-flow__edge-path").evaluateAll((elements) => elements.map((element) => element.getAttribute("d")));
  expect(new Set(paths).size).toBe(4);
  const search = page.getByRole("textbox", { name: "Search loaded relations" });
  await search.fill("no matching relation");
  const pane = graph.locator(".react-flow__pane");
  const box = (await pane.boundingBox())!;
  await page.mouse.move(box.x + 30, box.y + 30);
  await page.mouse.down();
  await page.mouse.move(box.x + 110, box.y + 80, { steps: 8 });
  await page.mouse.up();
  const viewport = graph.locator(".react-flow__viewport");
  const transform = await viewport.getAttribute("style");
  const edge = graph.locator(".react-flow__edge").first();
  const edgeId = await edge.getAttribute("data-id");
  const retainedGraph = await graph.elementHandle();
  for (const activation of ["mouse", "Enter", "Space"]) {
    if (activation === "mouse") {
      await search.focus();
      await expect(edge).not.toBeFocused();
      const point = await edge.locator(".react-flow__edge-path").evaluate((element) => {
        const path = element as SVGPathElement;
        const point = path.getPointAtLength(path.getTotalLength() / 2).matrixTransform(path.getScreenCTM()!);
        return { x: point.x, y: point.y };
      });
      await page.mouse.click(point.x, point.y);
    } else {
      await edge.focus();
      await page.keyboard.press(activation);
    }
    const detail = page.getByRole("region", { name: "Relation details", exact: true });
    await expect(detail).toBeVisible();
    await expect(page.getByRole("dialog")).toHaveCount(0);
    await expect(graph).toBeHidden();
    await expect(detail.getByRole("textbox")).toHaveCount(0);
    await expect(page.getByRole("button", { name: "Add relation", exact: true })).toHaveCount(0);
    await expect(detail.getByRole("button", { name: "Back to graph and index" })).toBeFocused();
    await page.keyboard.press("Tab");
    expect(await page.evaluate(() => document.activeElement?.closest("[hidden]") !== null)).toBe(false);
    await detail.getByRole("button", { name: "Back to graph and index" }).click();
    await expect(edge).toBeFocused();
    await expect(search).toHaveValue("no matching relation");
    expect(await retainedGraph!.evaluate((element) => element.isConnected)).toBe(true);
    await expect(viewport).toHaveAttribute("style", transform!);
    await expect(edge).toHaveAttribute("class", /selected/);
  }
  await search.fill("");
  await expect(page.locator('tr[aria-selected="true"]')).toHaveCount(1);
  await edge.focus();
  await page.keyboard.press("Enter");
  const detail = page.getByRole("region", { name: "Relation details", exact: true });
  await detail.getByRole("button", { name: "Edit", exact: true }).click();
  const edit = page.getByRole("region", { name: "Editing join", exact: true });
  await expect(edit.getByRole("combobox", { name: "Join kind" })).toBeFocused();
  await edit.getByRole("textbox", { name: "Evidence" }).fill("Discarded graph draft");
  await edit.getByRole("button", { name: "Cancel", exact: true }).click();
  const discard = page.getByRole("dialog");
  await expect(discard).toBeVisible();
  await discard.getByRole("button", { name: "Stay", exact: true }).click();
  await expect(edit.getByRole("textbox", { name: "Evidence" })).toHaveValue("Discarded graph draft");
  await edit.getByRole("button", { name: "Cancel", exact: true }).click();
  await discard.getByRole("button", { name: "Discard", exact: true }).click();
  await expect(detail).toBeVisible();
  await expect(detail).not.toContainText("Discarded graph draft");
  await detail.getByRole("button", { name: "Edit", exact: true }).click();
  await edit.getByRole("textbox", { name: "Evidence" }).fill("Saved graph evidence");
  await edit.getByRole("textbox", { name: "Join expression" }).fill("saved.graph.expression");
  await edit.getByRole("button", { name: "Save relation" }).click();
  await expect(detail).toContainText("Saved graph evidence");
  await expect(detail).toContainText("saved.graph.expression");
  const updated = await request.get(`/api/objects/${object}/joins`);
  expect((await updated.json()).items.find((join: { id: string }) => join.id === edgeId)).toMatchObject({ evidence: "Saved graph evidence", join_expression: "saved.graph.expression" });
  await detail.getByRole("button", { name: "Back to graph and index" }).click();
  await expect(edge).toBeFocused();
  await expect(viewport).toHaveAttribute("style", transform!);
  await page.screenshot({ path: test.info().outputPath("relations-graph.png") });
  await page.setViewportSize({ width: 640, height: 740 });
  await expect(graph).toBeVisible();
  await expect(page.getByRole("region", { name: "Relation index", exact: true })).toBeHidden();
  await page.locator("label").filter({ hasText: /^Relation index$/ }).click();
  await expect(page.getByRole("region", { name: "Relation index", exact: true })).toBeVisible();
  await expect(graph).toBeHidden();
  await page.screenshot({ path: test.info().outputPath("relations-index-narrow.png") });
  await page.locator("label").filter({ hasText: /^Relation graph$/ }).click();
  await page.getByRole("button", { name: "Fit", exact: true }).click();
  await page.screenshot({ path: test.info().outputPath("relations-graph-narrow.png") });
  await page.setViewportSize({ width: 1200, height: 600 });
  await expect(page.getByRole("region", { name: "Relation index", exact: true })).toBeHidden();
  await page.getByRole("button", { name: "Fit", exact: true }).click();
  await page.screenshot({ path: test.info().outputPath("relations-graph-short.png") });
});
