/** @vitest-environment jsdom */

import { MantineProvider } from "@mantine/core";
import { notifications, notificationsStore } from "@mantine/notifications";
import { act, cleanup, fireEvent, render, screen } from "@testing-library/react";
import { createElement, type ReactNode } from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { ChannelRuns } from "@/features/channels/ChannelRuns";
import type { ChannelRun } from "@/features/channels/types";
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
  listRuns: vi.fn(),
}));

vi.mock("@/features/channels/api", () => ({
  listRuns: (
    channelId: string,
    params?: { limit?: number; offset?: number },
    init?: { signal?: AbortSignal },
  ) => api.listRuns(channelId, params, init),
}));

vi.mock("@refinedev/core", () => ({
  useTranslate: () => (key: string, options?: Record<string, unknown>) => {
    const template = key === "status.freshness" ? "Last updated {{time}}" : key;
    if (!options) return template;
    return template.replace(/\{\{(\w+)\}\}/g, (_, name: string) => String(options[name] ?? ""));
  },
  useBreadcrumb: () => ({ breadcrumbs: [] }),
}));

vi.mock("next/link", () => ({
  default: ({ href, children }: { href: string; children: ReactNode }) =>
    createElement("a", { href }, children),
  useLinkStatus: () => ({ pending: false }),
}));

vi.mock("next/navigation", () => ({
  usePathname: () => "/console/channels/chn_1",
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

function run(status: string, message: string | null = null): ChannelRun {
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
    error_message: message,
  };
}

function page(items: ChannelRun[], total = items.length) {
  return { items, total, limit: 50, offset: 0 };
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

function renderRuns() {
  return render(
    createElement(
      MantineProvider,
      { env: "test" },
      createElement(ConsoleNotifications),
      createElement(ChannelRuns, { channelId: "chn_1" }),
    ),
  );
}

function politeRegion(): HTMLElement | null {
  return document.querySelector("[aria-live='polite']");
}

describe("ChannelRuns load feedback", () => {
  beforeEach(() => {
    vi.useFakeTimers();
    vi.setSystemTime(new Date("2026-10-11T06:00:29Z"));
    stubDom();
    resetNotifications();
    api.listRuns.mockReset();
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

  it("shows the unloaded list row and one notification when the first load gets no rows", async () => {
    bindClientI18n({
      t: (key: string) => (key === "feedback.repeated" ? "Repeated {{count}} times" : key),
    } as never);
    api.listRuns.mockImplementation(() => Promise.reject(upstream("req-runs")));
    renderRuns();

    await advance(0);
    expect(screen.getByRole("button", { name: "status.unloaded" })).toBeTruthy();
    expect(screen.queryByText("channels.runs.empty")).toBeNull();
    expect(screen.queryByText("liveStatus.unavailable")).toBeNull();
    expect(screen.queryByText("liveStatus.stale")).toBeNull();
    expect(screen.getAllByRole("alert")).toHaveLength(1);
    expect(screen.getByText("problems.unknown")).toBeTruthy();
    expect(screen.getByRole("button", { name: "common.retry" })).toBeTruthy();

    await advance(LIVE_STATUS_INTERVAL_MS);
    expect(api.listRuns.mock.calls.length).toBeGreaterThanOrEqual(2);
    expect(screen.getAllByRole("alert")).toHaveLength(1);
    expect(screen.queryByText("problems.unknown Repeated 2 times")).toBeNull();
  });

  it("notifies for a failed unloaded retry and not for the next poll", async () => {
    bindClientI18n({
      t: (key: string) => (key === "feedback.repeated" ? "Repeated {{count}} times" : key),
    } as never);
    api.listRuns.mockImplementation(() => Promise.reject(upstream("req-runs")));
    renderRuns();

    await advance(0);
    fireEvent.click(screen.getByRole("button", { name: "common.retry" }));
    await advance(0);
    expect(screen.getAllByRole("alert")).toHaveLength(1);
    expect(screen.getByText("problems.unknown Repeated 2 times")).toBeTruthy();

    await advance(LIVE_STATUS_INTERVAL_MS);
    expect(screen.queryByText("problems.unknown Repeated 3 times")).toBeNull();
  });

  it("keeps an empty list empty when the load succeeds", async () => {
    api.listRuns.mockResolvedValue(page([]));
    renderRuns();

    await advance(0);
    expect(screen.getByText("channels.runs.empty")).toBeTruthy();
    expect(screen.queryByRole("button", { name: "status.unloaded" })).toBeNull();
    expect(screen.queryAllByRole("alert")).toHaveLength(0);
  });

  it("replaces the status dot with a badge that shows freshness and does not notify", async () => {
    api.listRuns
      .mockResolvedValueOnce(page([run("running")]))
      .mockRejectedValueOnce(new Error("offline"))
      .mockResolvedValue(page([run("running")]));
    renderRuns();

    await advance(0);
    expect(screen.getByText("status.job.running")).toBeTruthy();
    expect(screen.queryByRole("img", { name: "status.job.running" })).toBeNull();
    expect(screen.queryByRole("button", { name: UPDATED })).toBeNull();
    expect(politeRegion()).toBeTruthy();
    expect(screen.queryAllByRole("alert")).toHaveLength(0);

    await advance(LIVE_STATUS_INTERVAL_MS);
    expect(api.listRuns).toHaveBeenCalledTimes(2);
    expect(screen.getByText("status.job.running")).toBeTruthy();
    expect(screen.queryByText("liveStatus.stale")).toBeNull();
    expect(screen.queryByText("liveStatus.unavailable")).toBeNull();
    expect(screen.queryByRole("button", { name: "status.unloaded" })).toBeNull();
    expect(screen.queryAllByRole("alert")).toHaveLength(0);

    fireEvent.click(screen.getByRole("button", { name: UPDATED }));
    await advance(0);
    expect(api.listRuns).toHaveBeenCalledTimes(3);
    expect(screen.queryByRole("button", { name: UPDATED })).toBeNull();
    expect(screen.getByText("status.job.running")).toBeTruthy();
    expect(screen.queryAllByRole("alert")).toHaveLength(0);
    expect(politeRegion()).toBeTruthy();
  });

  it("explains a run error on the status badge", async () => {
    api.listRuns.mockResolvedValue(page([run("failed", "writer rejected the row")]));
    renderRuns();

    await advance(0);
    const label = screen.getByText("status.job.failed");
    const badge = label.parentElement;
    if (!badge) throw new Error("missing status badge");
    fireEvent.mouseEnter(badge);
    expect(screen.getByRole("tooltip").textContent).toBe("writer rejected the row");
  });

  it("notifies when refreshing from the freshness marker fails, and not on the next poll", async () => {
    bindClientI18n({
      t: (key: string) => (key === "feedback.repeated" ? "Repeated {{count}} times" : key),
    } as never);
    api.listRuns
      .mockResolvedValueOnce(page([run("running")]))
      .mockImplementation(() => Promise.reject(upstream("req-2")));
    renderRuns();

    await advance(0);
    await advance(LIVE_STATUS_INTERVAL_MS);
    expect(screen.queryAllByRole("alert")).toHaveLength(0);

    fireEvent.click(screen.getByRole("button", { name: UPDATED }));
    await advance(0);
    expect(screen.getAllByRole("alert")).toHaveLength(1);
    expect(screen.getByText("status.job.running")).toBeTruthy();

    await advance(LIVE_STATUS_INTERVAL_MS);
    expect(screen.getAllByRole("alert")).toHaveLength(1);
    expect(screen.queryByText("problems.unknown Repeated 2 times")).toBeNull();
  });

  it("leaves freshness and unloaded off when the session has expired", async () => {
    api.listRuns
      .mockResolvedValueOnce(page([run("running")]))
      .mockRejectedValueOnce(
        new ApiError(401, "AUTH_UNAUTHENTICATED", "Sign in again", "req-session"),
      );
    renderRuns();

    await advance(0);
    await advance(LIVE_STATUS_INTERVAL_MS);
    expect(screen.getByText("status.job.running")).toBeTruthy();
    expect(screen.queryByRole("button", { name: UPDATED })).toBeNull();
    expect(screen.queryByText("liveStatus.stale")).toBeNull();
    expect(screen.queryAllByRole("alert")).toHaveLength(0);
  });

  it("does not notify or show unloaded when the first load expires the session", async () => {
    api.listRuns.mockRejectedValue(
      new ApiError(401, "AUTH_UNAUTHENTICATED", "Sign in again", "req-session"),
    );
    renderRuns();

    await advance(0);
    expect(screen.queryByRole("button", { name: "status.unloaded" })).toBeNull();
    expect(screen.queryByText("channels.runs.empty")).toBeNull();
    expect(screen.queryAllByRole("alert")).toHaveLength(0);

    await advance(LIVE_STATUS_INTERVAL_MS);
    expect(screen.queryAllByRole("alert")).toHaveLength(0);
    expect(screen.queryByRole("button", { name: "status.unloaded" })).toBeNull();
  });

  it("announces a later status in the polite live region", async () => {
    api.listRuns
      .mockResolvedValueOnce(page([run("running")]))
      .mockResolvedValue(page([run("succeeded")]));
    renderRuns();

    await advance(0);
    expect(politeRegion()?.textContent).toBe("");

    await advance(LIVE_STATUS_INTERVAL_MS);
    expect(politeRegion()?.textContent).toBe("status.job.succeeded");
  });
});
