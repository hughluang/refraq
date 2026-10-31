/** @vitest-environment jsdom */

import { MantineProvider } from "@mantine/core";
import { notifications, notificationsStore } from "@mantine/notifications";
import { act, cleanup, fireEvent, render, screen } from "@testing-library/react";
import { createElement } from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { JobDetailModal } from "@/features/jobs/JobDetailModal";
import type { Job } from "@/features/jobs/types";
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
  getJob: vi.fn(),
  getJobLogs: vi.fn(),
  cancelJob: vi.fn(),
}));

vi.mock("@/features/jobs/api", () => ({
  getJob: (jobId: string, init?: { signal?: AbortSignal }) => api.getJob(jobId, init),
  getJobLogs: (jobId: string, init?: { signal?: AbortSignal }) => api.getJobLogs(jobId, init),
  cancelJob: (jobId: string) => api.cancelJob(jobId),
}));

vi.mock("@refinedev/core", () => ({
  useTranslate: () => (key: string, options?: Record<string, unknown>) => {
    const template = key === "status.freshness" ? "Last updated {{time}}" : key;
    if (!options) return template;
    return template.replace(/\{\{(\w+)\}\}/g, (_, name: string) =>
      String(options[name] ?? ""),
    );
  },
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

function job(status: string): Job {
  return {
    id: "job_1",
    kind: "metadata.collect",
    status,
    input: {},
    result: {},
    summary: "Collect",
    trigger_kind: "user",
    trigger_ref: null,
    trigger_actor_name: "Ada",
    trigger_schedule_name: null,
    created_by_user_id: null,
    created_at: "2026-10-11T06:00:29Z",
    started_at: "2026-10-11T06:00:29Z",
    finished_at: null,
    error_code: null,
    error_message: null,
  };
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
  Element.prototype.scrollIntoView = () => {};
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
      createElement(JobDetailModal, {
        jobId: "job_1",
        opened: true,
        onClose: vi.fn(),
      }),
    ),
  );
}

describe("JobDetailModal", () => {
  beforeEach(() => {
    vi.useFakeTimers();
    vi.setSystemTime(new Date("2026-10-11T06:00:29Z"));
    stubDom();
    resetNotifications();
    api.getJob.mockReset();
    api.getJobLogs.mockReset();
    api.cancelJob.mockReset();
    api.getJobLogs.mockResolvedValue({ job_id: "job_1", body: "", updated_at: null });
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

  it("marks a stale job with the last update, refreshes on click, and does not notify", async () => {
    api.getJob
      .mockResolvedValueOnce({ job: job("running") })
      .mockRejectedValueOnce(new Error("offline"))
      .mockResolvedValue({ job: job("running") });
    renderDetail();

    await advance(0);
    expect(screen.getByText("job_1")).toBeTruthy();
    expect(screen.queryByRole("button", { name: UPDATED })).toBeNull();
    expect(screen.queryByText("liveStatus.stale")).toBeNull();
    expect(screen.queryAllByRole("alert")).toHaveLength(0);

    await advance(LIVE_STATUS_INTERVAL_MS);
    expect(api.getJob).toHaveBeenCalledTimes(2);
    const marker = screen.getByRole("button", { name: UPDATED });
    fireEvent.mouseEnter(marker);
    expect(screen.getByRole("tooltip").textContent).toBe(UPDATED);
    expect(screen.queryByText("liveStatus.stale")).toBeNull();
    expect(screen.queryByText("liveStatus.unavailable")).toBeNull();
    expect(screen.queryAllByRole("alert")).toHaveLength(0);

    fireEvent.click(marker);
    await advance(0);
    expect(api.getJob).toHaveBeenCalledTimes(3);
    expect(screen.queryByRole("button", { name: UPDATED })).toBeNull();
    expect(screen.queryAllByRole("alert")).toHaveLength(0);
  });

  it("notifies when refreshing from the freshness marker fails, and not on the next poll", async () => {
    bindClientI18n({
      t: (key: string) => (key === "feedback.repeated" ? "Repeated {{count}} times" : key),
    } as never);
    api.getJob
      .mockResolvedValueOnce({ job: job("running") })
      .mockImplementation(() =>
        Promise.reject(new ApiError(500, "NO_SUCH_CODE", "upstream timed out", "req-2")),
      );
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

  it("leaves the freshness marker off when the session has expired", async () => {
    api.getJob
      .mockResolvedValueOnce({ job: job("running") })
      .mockRejectedValueOnce(
        new ApiError(401, "AUTH_UNAUTHENTICATED", "Sign in again", "req-session"),
      );
    renderDetail();

    await advance(0);
    expect(screen.getByText("job_1")).toBeTruthy();

    await advance(LIVE_STATUS_INTERVAL_MS);
    expect(screen.getByText("job_1")).toBeTruthy();
    expect(screen.queryByRole("button", { name: UPDATED })).toBeNull();
    expect(screen.queryByText("liveStatus.stale")).toBeNull();
    expect(screen.queryByText("status.unloaded")).toBeNull();
    expect(screen.queryAllByRole("alert")).toHaveLength(0);
  });

  it("does not notify or show unloaded when the first load expires the session", async () => {
    api.getJob.mockRejectedValue(
      new ApiError(401, "AUTH_UNAUTHENTICATED", "Sign in again", "req-session"),
    );
    renderDetail();

    await advance(0);
    expect(screen.queryByRole("button", { name: "status.unloaded" })).toBeNull();
    expect(screen.queryByRole("button", { name: UPDATED })).toBeNull();
    expect(screen.queryAllByRole("alert")).toHaveLength(0);

    await advance(LIVE_STATUS_INTERVAL_MS);
    expect(screen.queryAllByRole("alert")).toHaveLength(0);
    expect(screen.queryByRole("button", { name: "status.unloaded" })).toBeNull();
  });

  it("shows unloaded and one retry notification when the first load never gets a job", async () => {
    api.getJob.mockImplementation(() =>
      Promise.reject(new ApiError(500, "NO_SUCH_CODE", "upstream timed out", "req-1")),
    );
    renderDetail();

    await advance(0);
    expect(screen.getByRole("button", { name: "status.unloaded" })).toBeTruthy();
    expect(screen.queryByText("job_1")).toBeNull();
    expect(screen.queryByText("liveStatus.unavailable")).toBeNull();
    expect(screen.getAllByRole("alert")).toHaveLength(1);
    expect(screen.getByText("problems.unknown")).toBeTruthy();
    expect(screen.getByRole("button", { name: "common.retry" })).toBeTruthy();

    await advance(LIVE_STATUS_INTERVAL_MS);
    expect(api.getJob.mock.calls.length).toBeGreaterThanOrEqual(2);
    expect(screen.getAllByRole("alert")).toHaveLength(1);
    expect(screen.getByText("problems.unknown")).toBeTruthy();
    expect(screen.queryByText(/feedback\.repeated/)).toBeNull();
  });

  it("notifies for a failed retry click and not for the next poll", async () => {
    bindClientI18n({
      t: (key: string) => (key === "feedback.repeated" ? "Repeated {{count}} times" : key),
    } as never);
    api.getJob.mockImplementation(() =>
      Promise.reject(new ApiError(500, "NO_SUCH_CODE", "upstream timed out", "req-1")),
    );
    renderDetail();

    await advance(0);
    expect(screen.getAllByRole("alert")).toHaveLength(1);
    expect(screen.getByText("problems.unknown")).toBeTruthy();

    await advance(LIVE_STATUS_INTERVAL_MS);
    expect(screen.getByText("problems.unknown")).toBeTruthy();
    expect(screen.queryByText("problems.unknown Repeated 2 times")).toBeNull();

    fireEvent.click(screen.getByRole("button", { name: "common.retry" }));
    await advance(0);
    expect(screen.getAllByRole("alert")).toHaveLength(1);
    expect(screen.getByText("problems.unknown Repeated 2 times")).toBeTruthy();

    await advance(LIVE_STATUS_INTERVAL_MS);
    expect(screen.getAllByRole("alert")).toHaveLength(1);
    expect(screen.getByText("problems.unknown Repeated 2 times")).toBeTruthy();
    expect(screen.queryByText("problems.unknown Repeated 3 times")).toBeNull();
  });

  it("clears unloaded after a successful retry and does not notify again", async () => {
    api.getJob
      .mockRejectedValueOnce(new ApiError(500, "NO_SUCH_CODE", "upstream timed out", "req-1"))
      .mockResolvedValue({ job: job("running") });
    renderDetail();

    await advance(0);
    fireEvent.click(screen.getByRole("button", { name: "status.unloaded" }));
    await advance(0);

    expect(screen.getByText("job_1")).toBeTruthy();
    expect(screen.queryByRole("button", { name: "status.unloaded" })).toBeNull();
    expect(screen.getAllByRole("alert")).toHaveLength(1);
    expect(screen.getByText("problems.unknown")).toBeTruthy();
    expect(screen.queryByText(/Repeated|feedback\.repeated/)).toBeNull();
  });

  it("announces a later status in the polite live region", async () => {
    api.getJob
      .mockResolvedValueOnce({ job: job("running") })
      .mockResolvedValue({ job: job("succeeded") });
    renderDetail();

    await advance(0);
    expect(screen.getByRole("status").textContent).toBe("");

    await advance(LIVE_STATUS_INTERVAL_MS);
    expect(screen.getByRole("status").textContent).toBe("status.job.succeeded");
  });
});
