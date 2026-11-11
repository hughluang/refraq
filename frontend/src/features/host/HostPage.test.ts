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
  tiles: { cpu: { online_count: 4, busy_share: 0.25 } },
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
  },
};

const hourBody = {
  span: "hour",
  start: "2026-11-11T23:00:00Z",
  end: "2026-11-12T00:00:00Z",
  step_seconds: 30,
  tiles: { cpu: { online_count: 8, busy_share: 0.5 } },
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
  },
};

const retainedBody = {
  span: "retained",
  start: "2026-10-28T00:00:00Z",
  end: "2026-11-12T00:00:00Z",
  step_seconds: 1803,
  tiles: { cpu: { online_count: 4, busy_share: 0.25 } },
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
});
