import { expect, test } from "@playwright/test";
import type { HostRead, HostSample, HostSpan } from "../src/features/host/types";
import { GENERATED_MODULE_CATALOG } from "../src/features/console/module-identity/generated-catalog";
import { expectAccessible } from "./axe";
import zh from "../src/locales/zh-CN/common.json";

const end = "2026-11-12T00:00:00Z";
const services = ["postgres", "redis", "api", "worker", "beat", "mcp", "entity-mcp", "web"];
const mount = `/data/${"long-resource-identity-".repeat(7)}`;
function fixture(span: HostSpan): HostRead {
  const step = span === "hour" ? 30 : span === "day" ? 121 : 1803;
  const samples = (...values: (number | null)[]): HostSample[] => values.map((v, i) => ({
    t: new Date(Date.parse(end) - (values.length - 1 - i) * step * 1000).toISOString(), v,
  }));
  const pressure = () => ({ waiting: samples(0, 0.1, null, 0.2), stalled: samples(0, 0, 0, 0) });
  return {
    span, start: new Date(Date.parse(end) - (span === "hour" ? 3600 : 86400) * 1000).toISOString(), end, step_seconds: step,
    tiles: { cpu: { online_count: 8, busy_share: 0.25 }, memory: { used_bytes: 2 ** 30, total_bytes: 2 ** 33 }, swap: { used_bytes: 0, total_bytes: 0 },
      filesystems: [{ mount, type: "ext4", used_bytes: 1024, total_bytes: 4096, used_share: 0.25, free_inodes: null }],
      postgres: { backends: 7, max_connections: 100 } },
    charts: {
      cpu_modes: [{ mode: "user", samples: samples(0.5, 0.5, null, 0.5) }, { mode: "guest_nice", samples: samples(0, 0, 0, 0) }, { mode: "dynamic-mode", samples: samples(0.02) }],
      run_queue: samples(1, 2, null, 0),
      filesystems: [{ mount, type: "ext4", available: samples(3072, 2048, 1024), delta: samples(null, -1024, -1024) }],
      disks: [{ device: "nvme0n1", busy_share: samples(0.1, 0.2), queue_length: samples(1) }],
      pressure: { cpu: pressure(), memory: pressure(), io: pressure() },
      postgres: { backends: samples(7), idle_in_transaction: samples(0), idle_in_transaction_aborted: [], checkpoint_timed: samples(11), checkpoint_requested: samples(4), checkpoint_write_time: samples(2500.5), checkpoint_sync_time: samples(12.5), checkpoint_buffers_written: samples(80), temp_files: samples(5), temp_bytes: samples(1500) },
      services: services.map((service, i) => ({ service, cpu_seconds: samples(i === 5 ? null : i), memory_bytes: samples(i === 5 ? null : i * 1024) })),
    },
  };
}

test.beforeEach(async ({ page, context, baseURL }) => {
  await context.addCookies([{ name: "refraq_sid", value: "synthetic-host-browser-session", url: baseURL! }, { name: "refraq.locale", value: "en-US", url: baseURL! }]);
  let user = { id: "host-e2e", account: "host-e2e", display_name: "Host acceptance", email: null, locale: "en-US", display_timezone: "UTC", role_id: null, role_key: "super_admin", role_name: null, identity_source: "local", permissions: ["console:access", "host:read"] };
  await page.route("**/api/**", async (route) => {
    const url = new URL(route.request().url());
    let body: unknown;
    if (url.pathname === "/api/auth/me") body = { user };
    else if (url.pathname === "/api/account/profile" && route.request().method() === "PATCH") {
      const patch = route.request().postDataJSON() as { locale: string };
      user = { ...user, locale: patch.locale };
      body = { user };
    }
    else if (url.pathname === "/api/console/module-identities") body = { modules: GENERATED_MODULE_CATALOG };
    else if (url.pathname === "/api/console/navigation") body = { groups: [{ id: "operations", label_key: "layout.navGroup.operations", modules: [{ id: "host", label_key: "host.title", route: "/console/host" }] }] };
    else if (url.pathname === "/api/host") body = fixture((url.searchParams.get("span") ?? "day") as HostSpan);
    else if (url.pathname === "/api/time-zones") body = { items: [{ id: "UTC", aliases: [] }] };
    else throw new Error(`Unexpected Host fixture request: ${route.request().method()} ${url.pathname}`);
    await route.fulfill({ json: body });
  });
});

for (const width of [1440, 390]) for (const colorScheme of ["light", "dark"] as const) {
  test(`Host ${width}px ${colorScheme}: inventory, layout, keyboard and reduced motion`, async ({ page }, testInfo) => {
    await page.setViewportSize({ width, height: 900 });
    await page.emulateMedia({ colorScheme, reducedMotion: "reduce" });
    await page.addInitScript((scheme) => localStorage.setItem("mantine-color-scheme-value", scheme), colorScheme);
    await page.goto("/console/host");
    await expect(page.locator("html")).toHaveAttribute("data-mantine-color-scheme", colorScheme);
    await expect(page.getByRole("heading", { level: 1, name: "Host", exact: true })).toBeVisible();
    await expect(page.getByRole("tab", { name: "Overview", exact: true })).toHaveAttribute("aria-selected", "true");
    await page.getByText("Advanced CPU modes", { exact: true }).click();
    await expect(page.getByRole("img", { name: "Run queue", exact: true })).toBeVisible();
    await expect(page.getByRole("img")).not.toHaveCount(0);
    const content = page.locator("[data-page-scroll]");
    expect(await content.evaluate((el) => el.scrollWidth <= el.clientWidth + 1)).toBe(true);
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
    await page.getByRole("tab", { name: "Services", exact: true }).click();
    for (const service of services) await expect(content.getByRole("checkbox", { name: service, exact: true })).toBeVisible();
    await expect(content.getByRole("img")).toHaveCount(2);
    await expectAccessible(page);
    await page.getByRole("tab", { name: "Storage", exact: true }).click();
    await expect(content.getByRole("option", { name: `${mount} (ext4)`, exact: true })).toHaveCount(1);
    await page.getByRole("combobox", { name: "Inspect resource history" }).selectOption(JSON.stringify(["disk", "nvme0n1"]));
    await expect(content.getByRole("img", { name: "nvme0n1 · Queue length" })).toBeVisible();
    expect(await content.evaluate((el) => el.scrollWidth <= el.clientWidth + 1)).toBe(true);
    await expectAccessible(page);
    await page.getByRole("tab", { name: "PostgreSQL", exact: true }).click();
    await expect(content.getByRole("img")).toHaveCount(3);
    await expectAccessible(page);
    await page.getByRole("tab", { name: "Overview", exact: true }).click();
    await page.screenshot({ path: testInfo.outputPath(`host-${width}-${colorScheme}.png`) });
    const summary = content.locator('[data-tab-panel="overview"] summary').filter({ hasText: "Recorded samples" }).first();
    const plot = content.getByRole("img").first();
    await plot.scrollIntoViewIfNeeded();
    const beforeHover = await plot.boundingBox();
    await plot.hover({ position: { x: 20, y: 70 } });
    await expect(summary.locator("..")).not.toHaveAttribute("open");
    await expect(content.getByRole("slider")).toHaveCount(0);
    const pointer = plot.locator("..").locator('[aria-hidden="true"]');
    await expect(pointer).toBeVisible();
    const overlay = await pointer.boundingBox();
    expect(overlay!.x).toBeGreaterThanOrEqual(beforeHover!.x);
    expect(overlay!.x + overlay!.width).toBeLessThanOrEqual(beforeHover!.x + beforeHover!.width + 1);
    expect((await plot.boundingBox())!.height).toBe(beforeHover!.height);
    await page.mouse.move(0, 0);
    await expect(pointer).toHaveCount(0);
    await summary.focus();
    await page.keyboard.press("Enter");
    const slider = content.getByRole("slider").first();
    await page.keyboard.press("Tab");
    await expect(slider).toBeFocused();
    await page.keyboard.press("End");
    await expect(slider).toHaveValue("3");
    await page.keyboard.press("Home");
    await expect(slider).toHaveValue("0");
    const refresh = page.getByRole("button", { name: "Refresh", exact: true });
    let release!: () => void;
    const pending = new Promise<void>((resolve) => { release = resolve; });
    let refreshReads = 0;
    await page.route("**/api/host?span=day", async (route) => {
      refreshReads += 1;
      await pending;
      await route.fulfill({ json: fixture("day") });
    });
    await refresh.focus();
    await page.keyboard.press("Enter");
    await expect(refresh).toHaveAttribute("aria-busy", "true");
    await expect(refresh).toHaveAttribute("aria-disabled", "true");
    await expect(refresh).toHaveAttribute("data-disabled");
    expect(await refresh.evaluate((button: HTMLButtonElement) => button.disabled)).toBe(false);
    await expect(refresh).toBeFocused();
    await page.keyboard.press("Enter");
    await page.keyboard.press("Space");
    expect(refreshReads).toBe(1);
    release();
    await expect(refresh).toHaveAttribute("aria-busy", "false");
    await expect(refresh).toBeEnabled();
    await expect(refresh).toBeFocused();
    expect(await content.evaluate((el) => el.getAnimations({ subtree: true }).length)).toBe(0);
    await expectAccessible(page);
  });
}

test("URL-driven reads expose loading and preserve retained panel interaction", async ({ page }) => {
  await page.goto("/console/host");
  await expect(page.getByRole("img", { name: "Run queue", exact: true })).toBeVisible();
  const disclosure = page.getByText("Advanced CPU modes", { exact: true });
  await disclosure.focus();
  await page.keyboard.press("Enter");
  await expect(page.getByRole("img", { name: "CPU modes (CPU-s/s)", exact: true })).toBeVisible();
  await page.keyboard.press("Space");
  await expect(page.getByRole("img", { name: "CPU modes (CPU-s/s)", exact: true })).toHaveCount(0);
  await page.getByRole("tab", { name: "Services", exact: true }).click();
  await page.getByRole("checkbox", { name: "worker", exact: true }).uncheck();
  let release!: () => void;
  const pending = new Promise<void>((resolve) => { release = resolve; });
  await page.route("**/api/host?span=hour", async (route) => {
    await pending;
    await route.fulfill({ json: fixture("hour") });
  });
  await page.evaluate(() => window.history.pushState(null, "", "/console/host?span=hour&tab=overview"));
  await expect(page.getByRole("status")).toHaveText("Loading: Last hour");
  await expect(page.getByRole("button", { name: "Refresh", exact: true })).toHaveAttribute("aria-busy", "true");
  await expect(page.getByText("Displayed history: Last 24 hours", { exact: true })).toBeVisible();
  release();
  await expect(page.getByRole("status")).toHaveText("Loaded: Last hour");
  await page.getByRole("tab", { name: "Services", exact: true }).click();
  await expect(page.getByRole("checkbox", { name: "worker", exact: true })).not.toBeChecked();
});

test("initial outage retries by keyboard without presenting invented zeros", async ({ page }) => {
  await page.route("**/api/host?span=day", (route) => route.fulfill({ status: 503, json: { status: 503, code: "HOST_SERIES_UNAVAILABLE" } }));
  await page.goto("/console/host");
  await expect(page.getByRole("button", { name: "Retry", exact: true }).first()).toBeVisible();
  await expect(page.locator("[data-page-scroll]").getByRole("img")).toHaveCount(0);
  await page.unroute("**/api/host?span=day");
  const retry = page.getByRole("button", { name: "Retry", exact: true }).first();
  await retry.focus();
  await page.keyboard.press("Enter");
  await expect(page.getByRole("img", { name: "Run queue", exact: true })).toBeVisible();
  await expect(page.getByText("Displayed history: Last 24 hours", { exact: true })).toBeVisible();
});

test("replacement failure retains the successful snapshot and keyboard retry reads selected span", async ({ page }) => {
  await page.goto("/console/host");
  await expect(page.getByRole("img", { name: "Run queue", exact: true })).toBeVisible();
  let release!: () => void;
  const pending = new Promise<void>((resolve) => { release = resolve; });
  await page.route("**/api/host?span=hour", async (route) => {
    await pending;
    await route.fulfill({ status: 503, contentType: "application/problem+json", body: JSON.stringify({ status: 503, code: "HOST_SERIES_UNAVAILABLE", detail: "Synthetic outage" }) });
  });
  await page.getByRole("combobox", { name: "History period" }).selectOption("hour");
  await expect(page.getByText("Displayed history: Last 24 hours", { exact: true })).toBeVisible();
  await expect(page.getByRole("button", { name: "Refresh", exact: true })).toBeDisabled();
  release();
  await expect(page.getByRole("button", { name: "Refresh", exact: true })).toBeEnabled();
  await expect(page.getByText("Displayed history: Last 24 hours", { exact: true })).toBeVisible();
  await page.unroute("**/api/host?span=hour");
  const retry = page.getByRole("button", { name: "Retry", exact: true }).first();
  await retry.focus();
  await page.keyboard.press("Enter");
  await expect(page.getByText("Displayed history: Last hour", { exact: true })).toBeVisible();
});

test("tablet rail navigation and system scheme retain the complete Host surface", async ({ page }, testInfo) => {
  await page.setViewportSize({ width: 820, height: 1000 });
  await page.addInitScript(() => localStorage.setItem("mantine-color-scheme-value", "auto"));
  await page.emulateMedia({ colorScheme: "dark", reducedMotion: "reduce" });
  await page.goto("/console/host");
  await expect(page.getByRole("img", { name: "Run queue", exact: true })).toBeVisible();
  await expect(page.locator("html")).toHaveAttribute("data-mantine-color-scheme", "dark");
  await page.getByRole("heading", { level: 1 }).focus();
  await page.keyboard.press("[");
  await expect(page.getByRole("button", { name: "Expand navigation", exact: true })).toBeVisible();
  await page.emulateMedia({ colorScheme: "light" });
  await expect(page.locator("html")).toHaveAttribute("data-mantine-color-scheme", "light");
  expect(await page.locator("[data-page-scroll]").evaluate((el) => el.scrollWidth <= el.clientWidth + 1)).toBe(true);
  await page.screenshot({ path: testInfo.outputPath("host-tablet-rail-system.png") });
  await expectAccessible(page);
});

test("Chinese locale at 200 percent text scale keeps Host controls and data readable", async ({ page }, testInfo) => {
  await page.setViewportSize({ width: 1440, height: 1000 });
  await page.goto("/console/host");
  await expect(page.getByRole("img", { name: "Run queue", exact: true })).toBeVisible();
  await page.getByRole("button", { name: "Language", exact: true }).click();
  await page.getByRole("menuitem", { name: "\u4e2d\u6587", exact: true }).click();
  await expect(page.getByRole("heading", { level: 1, name: zh["host.title"], exact: true })).toBeVisible();
  await page.evaluate(() => { document.documentElement.style.fontSize = "200%"; });
  const content = page.locator("[data-page-scroll]");
  expect(await content.evaluate((el) => el.scrollWidth <= el.clientWidth + 1)).toBe(true);
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
  await expect(page.getByRole("button", { name: zh["host.refresh"], exact: true })).toBeVisible();
  for (const plot of await content.getByRole("img").all()) {
    await expect.poll(() => plot.locator("text").evaluateAll((labels) => labels.every((label) => (label as SVGTextElement).getBBox().x >= 0))).toBe(true);
  }
  await page.screenshot({ path: testInfo.outputPath("host-zh-text-scale-200.png") });
  await expectAccessible(page);
});

test("empty retained store keeps all absent services without fabricating samples", async ({ page }) => {
  await page.route("**/api/host?span=retained", async (route) => {
    const body = fixture("retained");
    body.start = new Date(Date.parse(end) - 1296000 * 1000).toISOString();
    body.tiles = { cpu: { online_count: null, busy_share: null }, memory: { used_bytes: null, total_bytes: null }, swap: { used_bytes: null, total_bytes: null }, filesystems: [], postgres: { backends: null, max_connections: null } };
    body.charts.cpu_modes = [];
    body.charts.run_queue = [];
    body.charts.filesystems = [];
    body.charts.disks = [];
    body.charts.pressure = { cpu: { waiting: [], stalled: [] }, memory: { waiting: [], stalled: [] }, io: { waiting: [], stalled: [] } };
    for (const key of Object.keys(body.charts.postgres) as (keyof HostRead["charts"]["postgres"])[]) body.charts.postgres[key] = [];
    body.charts.services = services.map((service) => ({ service, cpu_seconds: [{ t: end, v: null }], memory_bytes: [{ t: end, v: null }] }));
    await route.fulfill({ json: body });
  });
  await page.goto("/console/host");
  await expect(page.getByRole("img", { name: "Run queue", exact: true })).toBeVisible();
  await page.getByRole("combobox", { name: "History period" }).selectOption("retained");
  await expect(page.getByText("Displayed history: Samples still in the store", { exact: true })).toBeVisible();
  const content = page.locator("[data-page-scroll]");
  await expect(content.getByRole("img")).toHaveCount(0);
  await page.getByRole("tab", { name: "Storage", exact: true }).click();
  await expect(content.getByText("No filesystem or disk observations in this history.", { exact: true })).toBeVisible();
  await page.getByRole("tab", { name: "Services", exact: true }).click();
  for (const service of services) await expect(content.getByRole("checkbox", { name: service, exact: true })).toBeVisible();
  await expect(content.locator("svg[data-series], svg [data-series]")).toHaveCount(0);
  await expect(content.getByRole("img")).toHaveCount(0);
});
