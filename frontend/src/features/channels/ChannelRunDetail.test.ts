/** @vitest-environment jsdom */

import { MantineProvider } from "@mantine/core";
import { notifications, notificationsStore } from "@mantine/notifications";
import { act, cleanup, fireEvent, render, screen } from "@testing-library/react";
import { createElement, type ReactNode } from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { ChannelRunDetail } from "@/features/channels/ChannelRunDetail";
import { EMPTY_GRAPH, type ChannelRun, type ChannelRunDetail as RunDetail } from "@/features/channels/types";
import { LIVE_STATUS_INTERVAL_MS } from "@/hooks/useLiveStatus";
import { ApiError } from "@/lib/api";
import { bindClientI18n } from "@/providers/i18n-runtime";
import { ConsoleNotifications } from "@/providers/notification-provider";
import {
  resetSessionStoreForTests,
  useSessionStore,
  type CurrentUser,
} from "@/providers/session-store";

const api = vi.hoisted(() => ({
  getRun: vi.fn(),
  listNodeTypes: vi.fn(),
  rerunRun: vi.fn(),
}));

vi.mock("@/features/channels/api", () => ({
  getRun: (channelId: string, jobId: string, init?: { signal?: AbortSignal }) =>
    api.getRun(channelId, jobId, init),
  listNodeTypes: () => api.listNodeTypes(),
  rerunRun: (channelId: string, jobId: string) => api.rerunRun(channelId, jobId),
}));

vi.mock("@/features/channels/ChannelCanvas", () => ({
  ChannelCanvas: () => null,
}));

vi.mock("@/features/channels/RunExecutionBrowser", () => ({
  RunExecutionBrowser: () => null,
}));

vi.mock("@refinedev/core", () => ({
  useTranslate: () => (key: string, options?: Record<string, unknown>) => {
    const template = key === "status.freshness" ? "Last updated {{time}}" : key;
    if (!options) return template;
    return template.replace(/\{\{(\w+)\}\}/g, (_, name: string) => String(options[name] ?? ""));
  },
  useNotification: () => ({ open: vi.fn() }),
  useCan: () => ({ data: { can: false } }),
  useBreadcrumb: () => ({ breadcrumbs: [] }),
}));

vi.mock("@/features/branding/BrandingProvider", () => ({
  useBranding: () => ({ brandName: "Refraq" }),
}));

vi.mock("next/link", () => ({
  default: ({ href, children }: { href: string; children: ReactNode }) =>
    createElement("a", { href }, children),
  useLinkStatus: () => ({ pending: false }),
}));

vi.mock("next/navigation", () => ({
  usePathname: () => "/console/channels/chn_1/runs/job_1",
  useRouter: () => ({ push: vi.fn(), replace: vi.fn(), refresh: vi.fn() }),
  useSearchParams: () => new URLSearchParams(),
}));

const UPDATED = "Last updated 10/11/2026, 6:00:29 AM";

const viewer: CurrentUser = {
  id: "usr_1",
  account: "ada",
  display_name: "Ada",
  email: null,
  locale: "en-US",
  display_timezone: "UTC",
  role_id: null,
  role_key: null,
  role_name: null,
  permissions: [],
  identity_source: "local",
};

function run(status: string): ChannelRun {
  return {
    job_id: "job_1",
    status,
    outcome: null,
    target: "published",
    version: 3,
    draft_revision: null,
    trigger_kind: "user",
    trigger_ref: null,
    trigger_node_id: "start",
    trigger_actor_name: "Ada",
    trigger_schedule_name: null,
    ignore_checkpoints: false,
    failed_node_id: null,
    created_at: "2026-10-11T06:00:29Z",
    started_at: "2026-10-11T06:00:29Z",
    finished_at: null,
    error_code: null,
    error_message: null,
  };
}

function detail(status: string): RunDetail {
  return { run: run(status), graph: EMPTY_GRAPH, node_summaries: [] };
}

function upstream(requestId: string) {
  return new ApiError(500, "NO_SUCH_CODE", "upstream timed out", requestId);
}

function resetNotifications() {
  const state = notificationsStore.getState();
  for (const item of [...state.notifications, ...state.queue]) {
    notifications.hide(item.id);
  }
  notifications.clean();
}

function stubDom() {
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
  vi.stubGlobal(
    "fetch",
    vi.fn(async (url: string) => {
      if (String(url).includes("/time-zones")) {
        return new Response(JSON.stringify({ items: [{ id: "UTC", aliases: [] }] }), {
          status: 200,
          headers: { "Content-Type": "application/json" },
        });
      }
      return new Response("not found", { status: 404 });
    }),
  );
}

async function advance(ms: number) {
  await act(async () => {
    await vi.advanceTimersByTimeAsync(ms);
  });
}

function renderDetail() {
  return render(
    createElement(
      MantineProvider,
      { env: "test" },
      createElement(ConsoleNotifications),
      createElement(ChannelRunDetail, { channelId: "chn_1", jobId: "job_1" }),
    ),
  );
}

function politeRegion(): HTMLElement | null {
  return document.querySelector("[aria-live='polite']");
}

describe("ChannelRunDetail load feedback", () => {
  beforeEach(() => {
    vi.useFakeTimers();
    vi.setSystemTime(new Date("2026-10-11T06:00:29Z"));
    stubDom();
    resetNotifications();
    api.getRun.mockReset();
    api.listNodeTypes.mockReset();
    api.rerunRun.mockReset();
    api.listNodeTypes.mockResolvedValue({ items: [] });
    useSessionStore.setState({
      user: viewer,
      permissionsReady: true,
      identityError: null,
      signedOutLocally: false,
    });
  });

  afterEach(() => {
    cleanup();
    resetNotifications();
    vi.unstubAllGlobals();
    resetSessionStoreForTests();
    bindClientI18n({ t: (key: string) => key } as never);
    vi.useRealTimers();
  });

  it("shows unloaded and one retry notification when the first load never gets a run", async () => {
    bindClientI18n({
      t: (key: string) => (key === "feedback.repeated" ? "Repeated {{count}} times" : key),
    } as never);
    api.getRun.mockImplementation(() => Promise.reject(upstream("req-1")));
    renderDetail();

    await advance(0);
    expect(screen.getByRole("button", { name: "status.unloaded" })).toBeTruthy();
    expect(screen.queryByText("liveStatus.unavailable")).toBeNull();
    expect(screen.queryByText("liveStatus.stale")).toBeNull();
    expect(screen.queryByText("common.error")).toBeNull();
    expect(screen.getAllByRole("alert")).toHaveLength(1);
    expect(screen.getByText("problems.unknown")).toBeTruthy();
    expect(screen.getByRole("button", { name: "common.retry" })).toBeTruthy();

    await advance(LIVE_STATUS_INTERVAL_MS);
    expect(api.getRun.mock.calls.length).toBeGreaterThanOrEqual(2);
    expect(screen.getAllByRole("alert")).toHaveLength(1);
    expect(screen.queryByText("problems.unknown Repeated 2 times")).toBeNull();
  });

  it("notifies for a failed retry click and not for the next poll", async () => {
    bindClientI18n({
      t: (key: string) => (key === "feedback.repeated" ? "Repeated {{count}} times" : key),
    } as never);
    api.getRun.mockImplementation(() => Promise.reject(upstream("req-1")));
    renderDetail();

    await advance(0);
    expect(screen.getAllByRole("alert")).toHaveLength(1);

    fireEvent.click(screen.getByRole("button", { name: "common.retry" }));
    await advance(0);
    expect(screen.getAllByRole("alert")).toHaveLength(1);
    expect(screen.getByText("problems.unknown Repeated 2 times")).toBeTruthy();

    await advance(LIVE_STATUS_INTERVAL_MS);
    expect(screen.getAllByRole("alert")).toHaveLength(1);
    expect(screen.queryByText("problems.unknown Repeated 3 times")).toBeNull();
  });

  it("clears unloaded after a successful retry and does not notify again", async () => {
    api.getRun.mockRejectedValueOnce(upstream("req-1")).mockResolvedValue(detail("running"));
    renderDetail();

    await advance(0);
    fireEvent.click(screen.getByRole("button", { name: "status.unloaded" }));
    await advance(0);

    expect(screen.getByText("status.job.running")).toBeTruthy();
    expect(screen.queryByRole("button", { name: "status.unloaded" })).toBeNull();
    expect(screen.getAllByRole("alert")).toHaveLength(1);
    expect(screen.queryByText(/Repeated|feedback\.repeated/)).toBeNull();
  });

  it("marks a loaded run stale without a notification and refreshes from the marker", async () => {
    api.getRun
      .mockResolvedValueOnce(detail("running"))
      .mockRejectedValueOnce(new Error("offline"))
      .mockResolvedValue(detail("running"));
    renderDetail();

    await advance(0);
    expect(screen.getByText("status.job.running")).toBeTruthy();
    expect(screen.queryByRole("button", { name: UPDATED })).toBeNull();
    expect(politeRegion()).toBeTruthy();
    expect(screen.queryAllByRole("alert")).toHaveLength(0);

    await advance(LIVE_STATUS_INTERVAL_MS);
    expect(api.getRun).toHaveBeenCalledTimes(2);
    expect(screen.getByText("status.job.running")).toBeTruthy();
    expect(screen.queryByText("liveStatus.stale")).toBeNull();
    expect(screen.queryByText("liveStatus.unavailable")).toBeNull();
    expect(screen.queryAllByRole("alert")).toHaveLength(0);
    const marker = screen.getByRole("button", { name: UPDATED });
    fireEvent.mouseEnter(marker);
    expect(screen.getByRole("tooltip").textContent).toBe(UPDATED);

    fireEvent.click(marker);
    await advance(0);
    expect(api.getRun).toHaveBeenCalledTimes(3);
    expect(screen.queryByRole("button", { name: UPDATED })).toBeNull();
    expect(screen.queryAllByRole("alert")).toHaveLength(0);
    expect(politeRegion()).toBeTruthy();
  });

  it("notifies when refreshing from the freshness marker fails, and not on the next poll", async () => {
    bindClientI18n({
      t: (key: string) => (key === "feedback.repeated" ? "Repeated {{count}} times" : key),
    } as never);
    api.getRun
      .mockResolvedValueOnce(detail("running"))
      .mockImplementation(() => Promise.reject(upstream("req-2")));
    renderDetail();

    await advance(0);
    await advance(LIVE_STATUS_INTERVAL_MS);
    expect(screen.queryAllByRole("alert")).toHaveLength(0);

    fireEvent.click(screen.getByRole("button", { name: UPDATED }));
    await advance(0);
    expect(screen.getAllByRole("alert")).toHaveLength(1);
    expect(screen.getByText("problems.unknown")).toBeTruthy();

    await advance(LIVE_STATUS_INTERVAL_MS);
    expect(screen.getAllByRole("alert")).toHaveLength(1);
    expect(screen.queryByText("problems.unknown Repeated 2 times")).toBeNull();
  });

  it("leaves freshness and unloaded off when the session has expired", async () => {
    api.getRun
      .mockResolvedValueOnce(detail("running"))
      .mockRejectedValueOnce(
        new ApiError(401, "AUTH_UNAUTHENTICATED", "Sign in again", "req-session"),
      );
    renderDetail();

    await advance(0);
    expect(screen.getByText("status.job.running")).toBeTruthy();

    await advance(LIVE_STATUS_INTERVAL_MS);
    expect(screen.getByText("status.job.running")).toBeTruthy();
    expect(screen.queryByRole("button", { name: UPDATED })).toBeNull();
    expect(screen.queryByText("liveStatus.stale")).toBeNull();
    expect(screen.queryByText("status.unloaded")).toBeNull();
    expect(screen.queryAllByRole("alert")).toHaveLength(0);
  });

  it("does not notify or show unloaded when the first load expires the session", async () => {
    api.getRun.mockRejectedValue(
      new ApiError(401, "AUTH_UNAUTHENTICATED", "Sign in again", "req-session"),
    );
    renderDetail();

    await advance(0);
    expect(screen.queryByRole("button", { name: "status.unloaded" })).toBeNull();
    expect(screen.queryAllByRole("alert")).toHaveLength(0);

    await advance(LIVE_STATUS_INTERVAL_MS);
    expect(screen.queryAllByRole("alert")).toHaveLength(0);
    expect(screen.queryByRole("button", { name: "status.unloaded" })).toBeNull();
  });

  it("shows an inbound run's kind and path", async () => {
    api.getRun.mockResolvedValue({
      ...detail("succeeded"),
      run: {
        ...run("succeeded"),
        trigger_kind: "inbound",
        trigger_ref: "payments/callback",
      },
    });
    renderDetail();

    await advance(0);
    expect(screen.getByText("channels.runs.trigger.inbound · payments/callback")).toBeTruthy();
  });

  it("leaves a user run without an inbound label", async () => {
    api.getRun.mockResolvedValue(detail("succeeded"));
    renderDetail();

    await advance(0);
    expect(screen.queryByText(/channels\.runs\.trigger\.inbound/)).toBeNull();
    expect(screen.queryByText("user")).toBeNull();
  });

  it("announces a later status in the polite live region", async () => {
    api.getRun.mockResolvedValueOnce(detail("running")).mockResolvedValue(detail("succeeded"));
    renderDetail();

    await advance(0);
    expect(politeRegion()?.textContent).toBe("");

    await advance(LIVE_STATUS_INTERVAL_MS);
    expect(politeRegion()?.textContent).toBe("status.job.succeeded");
  });
});
