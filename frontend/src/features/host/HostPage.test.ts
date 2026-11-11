/** @vitest-environment jsdom */

import { MantineProvider } from "@mantine/core";
import { notifications, notificationsStore } from "@mantine/notifications";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { createElement, type ReactNode } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { moduleIcon } from "@/components/icons";
import en from "@/locales/en-US/common.json";
import zh from "@/locales/zh-CN/common.json";
import { ConsoleNotifications } from "@/providers/notification-provider";

const copy = en as Record<string, string>;
const zhCopy = zh as Record<string, string>;

const CONFIRMED = [
  ["host.title", "Host", "\u4e3b\u673a"],
  ["host.span.hour", "Last hour", "\u6700\u8fd1\u4e00\u5c0f\u65f6"],
  ["host.span.day", "Last 24 hours", "\u6700\u8fd1 24 \u5c0f\u65f6"],
  ["host.span.retained", "Samples still in the store", "\u4ecd\u4fdd\u7559\u7684\u6837\u672c"],
  ["host.axis.now", "Now", "\u73b0\u5728"],
  ["host.cpu.online", "Online CPUs", "\u5728\u7ebf CPU"],
  ["host.cpu.busy", "CPU share", "CPU \u5360\u6bd4"],
  ["host.cpu.modes", "CPU modes", "CPU \u6a21\u5f0f"],
  ["host.cpu.runQueue", "Run queue", "\u8fd0\u884c\u961f\u5217"],
  ["host.memory.used", "Memory used", "\u5df2\u7528\u5185\u5b58"],
  ["host.memory.total", "Memory total", "\u5185\u5b58\u603b\u91cf"],
  ["host.swap.used", "Swap used", "\u5df2\u7528\u4ea4\u6362\u533a"],
  ["host.swap.total", "Swap total", "\u4ea4\u6362\u533a\u603b\u91cf"],
  ["host.filesystem.mount", "Mount", "\u6302\u8f7d\u70b9"],
  ["host.filesystem.type", "Type", "\u7c7b\u578b"],
  ["host.filesystem.used", "Used", "\u5df2\u7528"],
  ["host.filesystem.total", "Total", "\u603b\u91cf"],
  ["host.filesystem.share", "In use", "\u5df2\u7528\u6bd4\u4f8b"],
  ["host.filesystem.freeInodes", "Free inodes", "\u7a7a\u95f2 inode"],
  ["host.filesystem.available", "Available", "\u53ef\u7528\u7a7a\u95f4"],
  ["host.filesystem.delta", "Change since previous sample", "\u76f8\u5bf9\u4e0a\u4e00\u91c7\u6837\u7684\u53d8\u5316"],
  ["host.disk.device", "Disk", "\u78c1\u76d8"],
  ["host.disk.queue", "Queue length", "\u961f\u5217\u957f\u5ea6"],
  ["host.disk.busy", "Time doing I/O", "\u8fdb\u884c I/O \u7684\u65f6\u95f4"],
  ["host.pressure.cpu", "CPU pressure", "CPU \u538b\u529b"],
  ["host.pressure.memory", "Memory pressure", "\u5185\u5b58\u538b\u529b"],
  ["host.pressure.io", "I/O pressure", "I/O \u538b\u529b"],
  ["host.pressure.waiting", "Waiting", "\u7b49\u5f85"],
  ["host.pressure.stalled", "Stalled", "\u505c\u6ede"],
  [
    "problems.HOST_SERIES_UNAVAILABLE",
    "The host series could not be read. Occupancy is not shown.",
    "\u8bfb\u4e0d\u5230\u4e3b\u673a\u5e8f\u5217\uff0c\u753b\u9762\u4e0d\u663e\u793a\u5360\u7528\u3002",
  ],
] as const;

const dayBody = {
  span: "day",
  start: "2026-11-11T00:00:00Z",
  end: "2026-11-12T00:00:00Z",
  step_seconds: 121,
  tiles: {
    cpu: { online_count: 4, busy_share: 0.25 },
    memory: { used_bytes: 6100, total_bytes: 8192 },
    swap: { used_bytes: 128, total_bytes: 256 },
    filesystems: [
      {
        mount: "/data",
        type: "xfs",
        used_bytes: 750,
        total_bytes: 4000,
        used_share: 0.75,
        free_inodes: 42,
      },
    ],
  },
  charts: {
    cpu_modes: [
      {
        mode: "user",
        samples: [
          { t: "2026-11-11T00:00:00Z", v: 0.25 },
          { t: "2026-11-11T12:00:00Z", v: null },
          { t: "2026-11-12T00:00:00Z", v: 0.5 },
        ],
      },
    ],
    run_queue: [
      { t: "2026-11-11T00:00:00Z", v: 1 },
      { t: "2026-11-11T12:00:00Z", v: null },
      { t: "2026-11-12T00:00:00Z", v: 2 },
    ],
    filesystems: [
      {
        mount: "/data",
        type: "xfs",
        available: [
          { t: "2026-11-11T00:00:00Z", v: 300 },
          { t: "2026-11-11T12:00:00Z", v: null },
          { t: "2026-11-12T00:00:00Z", v: 333 },
        ],
        delta: [
          { t: "2026-11-11T00:00:00Z", v: null },
          { t: "2026-11-11T12:00:00Z", v: null },
          { t: "2026-11-12T00:00:00Z", v: -17 },
        ],
      },
    ],
    disks: [
      {
        device: "sda",
        busy_share: [
          { t: "2026-11-11T00:00:00Z", v: 0.2 },
          { t: "2026-11-11T12:00:00Z", v: null },
          { t: "2026-11-12T00:00:00Z", v: 0.2 },
        ],
        queue_length: [
          { t: "2026-11-11T00:00:00Z", v: 1.5 },
          { t: "2026-11-11T12:00:00Z", v: null },
          { t: "2026-11-12T00:00:00Z", v: 1.5 },
        ],
      },
    ],
    pressure: {
      cpu: {
        waiting: [
          { t: "2026-11-11T00:00:00Z", v: 0.11 },
          { t: "2026-11-11T12:00:00Z", v: null },
          { t: "2026-11-12T00:00:00Z", v: 0.11 },
        ],
        stalled: [],
      },
      memory: {
        waiting: [
          { t: "2026-11-11T00:00:00Z", v: 0.12 },
          { t: "2026-11-12T00:00:00Z", v: 0.12 },
        ],
        stalled: [
          { t: "2026-11-11T00:00:00Z", v: 0.13 },
          { t: "2026-11-12T00:00:00Z", v: 0.13 },
        ],
      },
      io: {
        waiting: [
          { t: "2026-11-11T00:00:00Z", v: 0.14 },
          { t: "2026-11-12T00:00:00Z", v: 0.14 },
        ],
        stalled: [
          { t: "2026-11-11T00:00:00Z", v: 0.15 },
          { t: "2026-11-12T00:00:00Z", v: 0.15 },
        ],
      },
    },
  },
};

const hourBody = {
  span: "hour",
  start: "2026-11-11T23:00:00Z",
  end: "2026-11-12T00:00:00Z",
  step_seconds: 30,
  tiles: {
    cpu: { online_count: 8, busy_share: 0.5 },
    memory: { used_bytes: 7000, total_bytes: 8192 },
    swap: { used_bytes: 64, total_bytes: 256 },
    filesystems: [
      {
        mount: "/var/log",
        type: "ext4",
        used_bytes: 90,
        total_bytes: 4000,
        used_share: 0.125,
        free_inodes: 11,
      },
    ],
  },
  charts: {
    cpu_modes: [
      {
        mode: "user",
        samples: [
          { t: "2026-11-11T23:00:00Z", v: 0.5 },
          { t: "2026-11-12T00:00:00Z", v: 0.5 },
        ],
      },
    ],
    run_queue: [
      { t: "2026-11-11T23:00:00Z", v: 3 },
      { t: "2026-11-12T00:00:00Z", v: 3 },
    ],
    filesystems: [
      {
        mount: "/var/log",
        type: "ext4",
        available: [
          { t: "2026-11-11T23:00:00Z", v: 80 },
          { t: "2026-11-12T00:00:00Z", v: 70 },
        ],
        delta: [
          { t: "2026-11-11T23:00:00Z", v: null },
          { t: "2026-11-12T00:00:00Z", v: -10 },
        ],
      },
    ],
    disks: [
      {
        device: "sdb",
        busy_share: [
          { t: "2026-11-11T23:00:00Z", v: 0.4 },
          { t: "2026-11-12T00:00:00Z", v: 0.4 },
        ],
        queue_length: [
          { t: "2026-11-11T23:00:00Z", v: 6 },
          { t: "2026-11-12T00:00:00Z", v: 6 },
        ],
      },
    ],
    pressure: {
      cpu: {
        waiting: [
          { t: "2026-11-11T23:00:00Z", v: 0.21 },
          { t: "2026-11-12T00:00:00Z", v: 0.21 },
        ],
        stalled: [],
      },
      memory: { waiting: [], stalled: [] },
      io: { waiting: [], stalled: [] },
    },
  },
};

const retainedBody = {
  span: "retained",
  start: "2026-10-28T00:00:00Z",
  end: "2026-11-12T00:00:00Z",
  step_seconds: 1803,
  tiles: {
    cpu: { online_count: 4, busy_share: 0.25 },
    memory: { used_bytes: 5000, total_bytes: 8192 },
    swap: { used_bytes: 128, total_bytes: 256 },
    filesystems: [
      {
        mount: "/srv",
        type: "xfs",
        used_bytes: 750,
        total_bytes: 4000,
        used_share: 0.75,
        free_inodes: 42,
      },
    ],
  },
  charts: {
    cpu_modes: [
      {
        mode: "user",
        samples: [
          { t: "2026-10-28T00:00:00Z", v: 0.25 },
          { t: "2026-11-12T00:00:00Z", v: 0.25 },
        ],
      },
    ],
    run_queue: [
      { t: "2026-10-28T00:00:00Z", v: 1 },
      { t: "2026-11-12T00:00:00Z", v: 1 },
    ],
    filesystems: [
      {
        mount: "/srv",
        type: "xfs",
        available: [
          { t: "2026-10-28T00:00:00Z", v: 300 },
          { t: "2026-11-12T00:00:00Z", v: 300 },
        ],
        delta: [
          { t: "2026-10-28T00:00:00Z", v: null },
          { t: "2026-11-12T00:00:00Z", v: null },
        ],
      },
    ],
    disks: [],
    pressure: {
      cpu: { waiting: [], stalled: [] },
      memory: { waiting: [], stalled: [] },
      io: { waiting: [], stalled: [] },
    },
  },
};

const fetchMock = vi.hoisted(() => vi.fn());

vi.mock("@refinedev/core", () => ({
  matchResourceFromRoute: () => ({ found: false }),
  useTranslate: () => (key: string) => copy[key] ?? key,
  useNotification: () => ({ open: vi.fn() }),
  useCan: () => ({ data: { can: true } }),
  usePermissions: () => ({ data: ["host:read"] as string[] }),
  useBreadcrumb: () => ({ breadcrumbs: [] }),
}));

vi.mock("@/features/branding/BrandingProvider", () => ({
  useBranding: () => ({ brandName: "Refraq" }),
}));

vi.mock("next/navigation", () => ({
  usePathname: () => "/console/host",
  useRouter: () => ({ push: vi.fn(), replace: vi.fn(), refresh: vi.fn() }),
  useSearchParams: () => new URLSearchParams(),
}));

vi.mock("next/link", () => ({
  default: ({ href, children }: { href: string; children?: ReactNode }) =>
    createElement("a", { href }, children),
  useLinkStatus: () => ({ pending: false }),
}));

function stubDomApis() {
  Object.defineProperty(window, "matchMedia", {
    writable: true,
    value: (query: string) => ({
      matches: false,
      media: query,
      addEventListener: vi.fn(),
      removeEventListener: vi.fn(),
    }),
  });
  class ResizeObserverStub {
    observe() {}
    unobserve() {}
    disconnect() {}
  }
  globalThis.ResizeObserver = ResizeObserverStub;
}

function resetNotifications() {
  const state = notificationsStore.getState();
  for (const item of [...state.notifications, ...state.queue]) {
    notifications.hide(item.id);
  }
  notifications.clean();
}

function jsonResponse(body: unknown, status = 200) {
  return Promise.resolve(
    new Response(JSON.stringify(body), {
      status,
      headers: {
        "content-type": status === 200 ? "application/json" : "application/problem+json",
      },
    }),
  );
}

function requestedSpan(call: unknown[]): string | null {
  const url = new URL(String(call[0]), "http://console.local");
  expect(url.pathname).toBe("/api/host");
  expect([...url.searchParams.keys()]).toEqual(["span"]);
  return url.searchParams.get("span");
}

function shell(node: ReactNode) {
  return createElement(MantineProvider, { env: "test" }, createElement(ConsoleNotifications), node);
}

async function renderPage() {
  const { HostPage } = await import("@/features/host/HostPage");
  render(shell(createElement(HostPage)));
}

describe("HostPage", () => {
  beforeEach(() => {
    stubDomApis();
    fetchMock.mockReset();
    vi.stubGlobal("fetch", fetchMock);
    resetNotifications();
  });

  afterEach(() => {
    cleanup();
    resetNotifications();
    vi.unstubAllGlobals();
  });

  it("keeps the confirmed copy in both catalogs", () => {
    for (const [key, english, chinese] of CONFIRMED) {
      expect(copy[key]).toBe(english);
      expect(zhCopy[key]).toBe(chinese);
    }
  });

  it("maps chart-bar to a real icon", () => {
    const chosen = renderToStaticMarkup(createElement(moduleIcon("chart-bar")));
    const fallback = renderToStaticMarkup(createElement(moduleIcon("not-a-real-icon")));
    expect(chosen).not.toBe(fallback);
  });

  it("opens on the last 24 hours and follows the selected span", async () => {
    fetchMock.mockImplementation((input: RequestInfo) => {
      const span = new URL(String(input), "http://console.local").searchParams.get("span");
      if (span === "hour") return jsonResponse(hourBody);
      if (span === "retained") return jsonResponse(retainedBody);
      return jsonResponse(dayBody);
    });
    await renderPage();

    expect(await screen.findByText("4")).toBeTruthy();
    expect(screen.getByRole("heading", { name: "Host" })).toBeTruthy();
    expect(requestedSpan(fetchMock.mock.calls[0] ?? [])).toBe("day");
    expect(screen.getByText("Online CPUs")).toBeTruthy();
    expect(screen.getByText("CPU share")).toBeTruthy();
    expect(screen.getByText("25%")).toBeTruthy();
    expect(screen.getByText("user")).toBeTruthy();
    expect(screen.getByText("2")).toBeTruthy();
    expect(screen.getByText("Memory used")).toBeTruthy();
    expect(screen.getByText("6100")).toBeTruthy();
    expect(screen.getByText("8192")).toBeTruthy();
    expect(screen.getByText("Swap used")).toBeTruthy();
    expect(screen.getByText("128")).toBeTruthy();
    expect(screen.getByText("256")).toBeTruthy();
    expect(screen.getByText("/data")).toBeTruthy();
    expect(screen.getByText("xfs")).toBeTruthy();
    expect(screen.getByText("750")).toBeTruthy();
    expect(screen.getByText("4000")).toBeTruthy();
    expect(screen.getByText("75%")).toBeTruthy();
    expect(screen.getByText("42")).toBeTruthy();
    expect(screen.getByText("333")).toBeTruthy();
    expect(screen.getByText("-17")).toBeTruthy();
    expect(screen.getByText("sda")).toBeTruthy();
    expect(screen.getByText("0.2")).toBeTruthy();
    expect(screen.getByText("1.5")).toBeTruthy();
    expect(screen.getByText("CPU pressure")).toBeTruthy();
    expect(screen.getByText("Memory pressure")).toBeTruthy();
    expect(screen.getByText("I/O pressure")).toBeTruthy();
    expect(screen.getAllByText("Waiting").length).toBeGreaterThan(0);
    expect(screen.getAllByText("Stalled").length).toBeGreaterThan(0);
    expect(screen.getByText("0.11")).toBeTruthy();
    expect(screen.getByText("0.13")).toBeTruthy();
    expect(screen.queryByText("0")).toBeNull();
    const space = screen.getByRole("img", { name: "/data" });
    expect(space.querySelectorAll("polyline")).toHaveLength(3);
    expect(screen.getAllByText("Now").length).toBeGreaterThan(0);
    expect(screen.getAllByText("-24h").length).toBeGreaterThan(0);
    expect(screen.getAllByText("-12h").length).toBeGreaterThan(0);
    const modes = screen.getByRole("img", { name: "CPU modes" });
    expect(modes.querySelectorAll("polyline")).toHaveLength(2);
    expect(screen.queryByText("0")).toBeNull();
    expect(screen.queryByText(/forecast/i)).toBeNull();
    expect(screen.queryByText(/shm_size|shared_buffers|work_mem|effective_cache_size/)).toBeNull();

    fireEvent.click(screen.getByRole("radio", { name: "Last hour" }));
    await waitFor(() => {
      expect(screen.getByText("8")).toBeTruthy();
    });
    const hourCall = fetchMock.mock.calls.at(-1) ?? [];
    expect(requestedSpan(hourCall)).toBe("hour");
    expect(screen.getByText("50%")).toBeTruthy();
    expect(screen.getByText("7000")).toBeTruthy();
    expect(screen.getByText("/var/log")).toBeTruthy();
    expect(screen.getByText("sdb")).toBeTruthy();
    expect(screen.getByText("0.21")).toBeTruthy();
    expect(screen.queryByText("6100")).toBeNull();
    expect(screen.queryByText("/data")).toBeNull();
    expect(screen.queryByText("sda")).toBeNull();
    expect(screen.getAllByText("-1h").length).toBeGreaterThan(0);
    expect(screen.getAllByText("-30m").length).toBeGreaterThan(0);
    expect(screen.queryByText("-24h")).toBeNull();

    fireEvent.click(screen.getByRole("radio", { name: "Samples still in the store" }));
    await waitFor(() => {
      expect(screen.getAllByText("-360h").length).toBeGreaterThan(0);
    });
    expect(requestedSpan(fetchMock.mock.calls.at(-1) ?? [])).toBe("retained");
    expect(document.body.textContent ?? "").not.toMatch(/\d+\s*days?/i);
  });

  it("shows the series failure and does not draw zeros", async () => {
    fetchMock.mockImplementation(() =>
      jsonResponse(
        {
          type: "urn:refraq:problem:HOST_SERIES_UNAVAILABLE",
          status: 503,
          code: "HOST_SERIES_UNAVAILABLE",
          detail: "The host series could not be read.",
          request_id: "req-host",
        },
        503,
      ),
    );
    await renderPage();

    expect(
      await screen.findByText("The host series could not be read. Occupancy is not shown."),
    ).toBeTruthy();
    expect(requestedSpan(fetchMock.mock.calls[0] ?? [])).toBe("day");
    expect(screen.queryByRole("img", { name: "CPU modes" })).toBeNull();
    expect(screen.queryByRole("img", { name: "Run queue" })).toBeNull();
    expect(screen.queryByText("0")).toBeNull();
    expect(screen.queryByText("0%")).toBeNull();
    expect(screen.queryByText("4")).toBeNull();
  });

  it("shows a zero swap reading and an empty inode count", async () => {
    fetchMock.mockImplementation(() =>
      jsonResponse({
        ...dayBody,
        tiles: {
          ...dayBody.tiles,
          swap: { used_bytes: 0, total_bytes: 0 },
          filesystems: [
            {
              mount: "/data",
              type: "xfs",
              used_bytes: 750,
              total_bytes: 4000,
              used_share: 0.75,
              free_inodes: null,
            },
          ],
        },
      }),
    );
    await renderPage();
    expect(await screen.findByText("Swap used")).toBeTruthy();
    expect(screen.getAllByText("0")).toHaveLength(2);
    expect(screen.getByText("—")).toBeTruthy();
    expect(screen.queryByText(/shm_size|shared_buffers|work_mem|effective_cache_size/)).toBeNull();
  });
});
