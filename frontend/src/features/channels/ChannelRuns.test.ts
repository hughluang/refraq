/** @vitest-environment jsdom */

import { MantineProvider } from "@mantine/core";
import { notifications, notificationsStore } from "@mantine/notifications";
import { act, cleanup, fireEvent, render, screen, within } from "@testing-library/react";
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

const jobs = vi.hoisted(() => ({
  cancelJob: vi.fn(),
}));

const access = vi.hoisted(() => ({
  grants: new Set<string>(),
}));

const i18n = vi.hoisted(() => ({
  extra: {} as Record<string, string>,
}));

vi.mock("@/features/channels/api", () => ({
  listRuns: (
    channelId: string,
    params?: { limit?: number; offset?: number },
    init?: { signal?: AbortSignal },
  ) => api.listRuns(channelId, params, init),
}));

vi.mock("@/features/jobs/api", () => ({
  cancelJob: (jobId: string) => jobs.cancelJob(jobId),
}));

vi.mock("@refinedev/core", () => ({
  useTranslate: () => (key: string, options?: Record<string, unknown>) => {
    const template =
      key === "status.freshness" ? "Last updated {{time}}" : (i18n.extra[key] ?? key);
    if (!options) return template;
    return template.replace(/\{\{(\w+)\}\}/g, (_, name: string) => String(options[name] ?? ""));
  },
  useCan: (request: { resource: string; action: string }) => ({
    data: { can: access.grants.has(`${request.resource}:${request.action}`) },
  }),
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
    i18n.extra = {};
    access.grants.clear();
    api.listRuns.mockReset();
    jobs.cancelJob.mockReset();
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

  it("shows status, start time, and duration, and opens the run from the start time", async () => {
    api.listRuns.mockResolvedValue(
      page([
        {
          ...run("running"),
          job_id: "job_run",
          trigger_kind: "inbound",
          trigger_ref: "payments/callback",
          ignore_checkpoints: true,
          target: "draft",
        },
        {
          ...run("succeeded"),
          job_id: "job_done",
          started_at: "2026-10-11T06:00:00Z",
          finished_at: "2026-10-11T06:01:00Z",
        },
        {
          ...run("queued"),
          job_id: "job_wait",
          started_at: null,
          created_at: "2026-10-11T05:00:00Z",
        },
      ]),
    );
    renderRuns();

    await advance(0);
    expect(screen.getByText("jobs.fields.duration: 0ms")).toBeTruthy();
    expect(screen.getByText("jobs.fields.duration: 1m")).toBeTruthy();
    expect(screen.getByText("jobs.fields.duration: —")).toBeTruthy();
    const openRun = screen.getByRole("link", { name: "10/11/2026, 6:00:29 AM" });
    expect(openRun.getAttribute("href")).toBe("/console/channels/chn_1/runs/job_run");
    expect(screen.getByText("status.job.running").closest("a")).toBeNull();
    expect(screen.getByText("channels.runs.trigger.inbound · payments/callback")).toBeTruthy();
    expect(screen.getByText("channels.runs.ignoreCheckpoints")).toBeTruthy();
    expect(screen.getByRole("img", { name: "channels.runs.subject.draft" })).toBeTruthy();

    await advance(LIVE_STATUS_INTERVAL_MS);
    expect(screen.getByText("jobs.fields.duration: 2s")).toBeTruthy();
    expect(screen.queryByText("jobs.fields.duration: 0ms")).toBeNull();
    expect(screen.getByText("jobs.fields.duration: 1m")).toBeTruthy();
    expect(screen.getByText("jobs.fields.duration: —")).toBeTruthy();
  });

  it("names the failed node and states the error the way the run detail header does", async () => {
    i18n.extra["problems.CHANNEL_NODE_FAILED"] = "A node failed";
    const untilSentence = "Until iteration output exceeds 16 MiB.";
    api.listRuns.mockResolvedValue(
      page([
        {
          ...run("failed"),
          job_id: "job_fail",
          failed_node_id: "node_writer",
          error_code: "CHANNEL_NODE_FAILED",
          error_message: "writer rejected the row",
          finished_at: "2026-10-11T06:00:30Z",
        },
        {
          ...run("failed"),
          job_id: "job_until",
          failed_node_id: null,
          error_code: "CHANNEL_ITERATION_VOLUME_EXCEEDED",
          error_message: untilSentence,
          started_at: "2026-10-11T06:00:00Z",
          finished_at: "2026-10-11T06:00:01Z",
        },
      ]),
    );
    renderRuns();

    await advance(0);
    expect(screen.getByText("node_writer")).toBeTruthy();
    expect(screen.getByText("A node failed")).toBeTruthy();
    expect(screen.getByText("writer rejected the row")).toBeTruthy();
    expect(screen.getAllByText(untilSentence)).toHaveLength(1);
    expect(screen.queryByText("node_until")).toBeNull();

    const label = screen.getAllByText("status.job.failed")[0];
    const badge = label?.parentElement;
    if (!badge) throw new Error("missing status badge");
    fireEvent.mouseEnter(badge);
    expect(screen.getByRole("tooltip").textContent).toBe("A node failed");
  });

  it("names the stop node on a cancelled row and states an error when one is present", async () => {
    i18n.extra["channels.runDetail.stoppedAt"] = "Stopped at {{node}}";
    i18n.extra["problems.CHANNEL_NODE_FAILED"] = "A node failed";
    api.listRuns.mockResolvedValue(
      page([
        {
          ...run("cancelled"),
          job_id: "job_stop",
          stopped_node_id: "node_stop",
          failed_node_id: "node_writer",
          error_code: "CHANNEL_NODE_FAILED",
          error_message: "writer rejected the row",
          finished_at: "2026-10-11T06:00:40Z",
        },
        {
          ...run("cancelled"),
          job_id: "job_quiet",
          stopped_node_id: null,
          started_at: "2026-10-11T06:00:00Z",
          finished_at: "2026-10-11T06:00:01Z",
        },
        {
          ...run("failed"),
          job_id: "job_fail",
          failed_node_id: "node_writer",
          stopped_node_id: "node_failstop",
          started_at: "2026-10-11T05:00:00Z",
          finished_at: "2026-10-11T05:00:01Z",
        },
      ]),
    );
    renderRuns();

    await advance(0);
    expect(screen.getByText("Stopped at node_stop")).toBeTruthy();
    expect(screen.getAllByText(/Stopped at /)).toHaveLength(1);
    expect(screen.getByText("A node failed")).toBeTruthy();
    expect(screen.getByText("writer rejected the row")).toBeTruthy();
    expect(screen.getAllByText("node_writer")).toHaveLength(1);
    expect(screen.getByRole("link", { name: "10/11/2026, 6:00:00 AM" }).getAttribute("href")).toBe(
      "/console/channels/chn_1/runs/job_quiet",
    );
  });

  it("shows only status, start time, and duration on a row that is not failed or cancelled", async () => {
    i18n.extra["problems.CHANNEL_NODE_FAILED"] = "A node failed";
    i18n.extra["channels.runDetail.stoppedAt"] = "Stopped at {{node}}";
    api.listRuns.mockResolvedValue(
      page([
        {
          ...run("succeeded"),
          job_id: "job_ok",
          failed_node_id: "node_hidden",
          stopped_node_id: "node_stop",
          error_code: "CHANNEL_NODE_FAILED",
          error_message: "writer rejected the row",
          finished_at: "2026-10-11T06:00:30Z",
        },
      ]),
    );
    renderRuns();

    await advance(0);
    expect(screen.getByText("status.job.succeeded")).toBeTruthy();
    expect(screen.getByRole("link", { name: "10/11/2026, 6:00:29 AM" }).getAttribute("href")).toBe(
      "/console/channels/chn_1/runs/job_ok",
    );
    expect(screen.getByText("jobs.fields.duration: 1s")).toBeTruthy();
    expect(screen.queryByText("node_hidden")).toBeNull();
    expect(screen.queryByText("Stopped at node_stop")).toBeNull();
    expect(screen.queryByText("A node failed")).toBeNull();
    expect(screen.queryByText("writer rejected the row")).toBeNull();

    const badge = screen.getByText("status.job.succeeded").parentElement;
    if (!badge) throw new Error("missing status badge");
    fireEvent.mouseEnter(badge);
    expect(screen.getByRole("tooltip").textContent).toBe("A node failed");
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

  it("shows an inbound run's kind and path and leaves other trigger labels unchanged", async () => {
    api.listRuns.mockResolvedValue(
      page([
        {
          ...run("succeeded"),
          job_id: "job_in",
          trigger_kind: "inbound",
          trigger_ref: "payments/callback",
        },
        {
          ...run("succeeded"),
          job_id: "job_user",
          trigger_kind: "user",
          trigger_ref: "user_1",
          trigger_actor_name: "Ada",
        },
        {
          ...run("succeeded"),
          job_id: "job_sched",
          trigger_kind: "schedule",
          trigger_ref: "sched_1",
          trigger_schedule_name: "Nightly",
        },
        {
          ...run("succeeded"),
          job_id: "job_retry",
          trigger_kind: "retry",
          trigger_ref: "job_source",
        },
        {
          ...run("failed"),
          job_id: "job_error",
          trigger_kind: "error",
          trigger_ref: "job_source",
        },
      ]),
    );
    renderRuns();

    await advance(0);
    expect(screen.getByText("channels.runs.trigger.inbound · payments/callback")).toBeTruthy();
    expect(screen.queryByText("user_1")).toBeNull();
    expect(screen.queryByText("Ada")).toBeNull();
    expect(screen.queryByText("sched_1")).toBeNull();
    expect(screen.queryByText("Nightly")).toBeNull();
    expect(screen.queryByText("retry")).toBeNull();
    expect(screen.queryByText("error")).toBeNull();
    expect(screen.queryByText("job_source")).toBeNull();
  });

  it("announces each later run by the start time on its row and by its status", async () => {
    api.listRuns
      .mockResolvedValueOnce(page([run("running")]))
      .mockResolvedValue(
        page([
          {
            ...run("succeeded"),
            job_id: "job_done",
            created_at: "2026-10-11T05:00:00Z",
            started_at: "2026-10-11T06:00:29Z",
          },
          {
            ...run("failed"),
            job_id: "job_fail",
            created_at: "2026-10-11T05:00:00Z",
            started_at: null,
          },
        ]),
      );
    renderRuns();

    await advance(0);
    expect(politeRegion()?.textContent).toBe("");

    await advance(LIVE_STATUS_INTERVAL_MS);
    expect(screen.getByRole("link", { name: "10/11/2026, 6:00:29 AM" })).toBeTruthy();
    expect(screen.getByRole("link", { name: "10/11/2026, 5:00:00 AM" })).toBeTruthy();
    expect(politeRegion()?.textContent).toBe(
      "10/11/2026, 6:00:29 AM status.job.succeeded, 10/11/2026, 5:00:00 AM status.job.failed",
    );
  });

  it("stops a non-terminal row by the start time on that row and does not open the run", async () => {
    access.grants.add("channels:edit");
    i18n.extra["channels.run.stop.confirmTitle"] = "Stop {{name}}?";
    i18n.extra["feedback.confirm.body"] = "{{record}}: {{consequence}}";
    api.listRuns.mockResolvedValue(
      page([
        {
          ...run("queued"),
          job_id: "job_wait",
          started_at: null,
          created_at: "2026-10-11T05:00:00Z",
        },
        {
          ...run("running"),
          job_id: "job_live",
          started_at: "2026-10-11T06:00:29Z",
        },
        { ...run("succeeded"), job_id: "job_ok", started_at: "2026-10-11T04:00:00Z" },
        { ...run("failed"), job_id: "job_fail", started_at: "2026-10-11T03:00:00Z" },
        { ...run("cancelled"), job_id: "job_stop", started_at: "2026-10-11T02:00:00Z" },
      ]),
    );
    renderRuns();

    await advance(0);
    const queued = screen.getByRole("link", { name: "10/11/2026, 5:00:00 AM" });
    const running = screen.getByRole("link", { name: "10/11/2026, 6:00:29 AM" });
    expect(queued.getAttribute("href")).toBe("/console/channels/chn_1/runs/job_wait");
    expect(within(queued.closest("tr") as HTMLElement).getByRole("button", { name: "channels.run.stop" })).toBeTruthy();
    expect(within(running.closest("tr") as HTMLElement).getByRole("button", { name: "channels.run.stop" })).toBeTruthy();
    for (const when of ["10/11/2026, 4:00:00 AM", "10/11/2026, 3:00:00 AM", "10/11/2026, 2:00:00 AM"]) {
      const row = screen.getByRole("link", { name: when }).closest("tr") as HTMLElement;
      expect(within(row).queryByRole("button", { name: "channels.run.stop" })).toBeNull();
    }

    fireEvent.click(
      within(queued.closest("tr") as HTMLElement).getByRole("button", { name: "channels.run.stop" }),
    );
    const dialog = screen.getByRole("dialog", { name: "Stop 10/11/2026, 5:00:00 AM?" });
    const shown = "10/11/2026, 5:00:00 AM";
    expect(dialog.textContent?.split(shown).length).toBe(3);
    expect(dialog.textContent).not.toContain("10/11/2026, 6:00:29 AM");
    expect(queued.getAttribute("href")).toBe("/console/channels/chn_1/runs/job_wait");
    expect(screen.getByRole("link", { name: shown })).toBe(queued);
  });

  it("cancels that row's job and reloads the list before the next poll", async () => {
    access.grants.add("channels:edit");
    i18n.extra["channels.run.stop.confirmTitle"] = "Stop {{name}}?";
    api.listRuns.mockResolvedValue(
      page([
        {
          ...run("running"),
          job_id: "job_live",
          started_at: "2026-10-11T06:00:29Z",
        },
        {
          ...run("queued"),
          job_id: "job_wait",
          started_at: null,
          created_at: "2026-10-11T05:00:00Z",
        },
      ]),
    );
    jobs.cancelJob.mockResolvedValue({ job: { id: "job_wait" } });
    renderRuns();

    await advance(0);
    expect(api.listRuns).toHaveBeenCalledTimes(1);
    const row = screen.getByRole("link", { name: "10/11/2026, 5:00:00 AM" }).closest("tr") as HTMLElement;
    fireEvent.click(within(row).getByRole("button", { name: "channels.run.stop" }));
    fireEvent.click(
      within(screen.getByRole("dialog", { name: "Stop 10/11/2026, 5:00:00 AM?" })).getByRole(
        "button",
        { name: "channels.run.stop" },
      ),
    );
    await advance(0);

    expect(jobs.cancelJob).toHaveBeenCalledTimes(1);
    expect(jobs.cancelJob).toHaveBeenCalledWith("job_wait");
    expect(api.listRuns).toHaveBeenCalledTimes(2);
    expect(api.listRuns.mock.calls[1]?.[0]).toBe("chn_1");
  });

  it("offers Stop when the caller can list jobs, and hides it when they can do neither", async () => {
    api.listRuns.mockResolvedValue(page([run("running")]));
    const view = renderRuns();
    await advance(0);
    expect(screen.queryByRole("button", { name: "channels.run.stop" })).toBeNull();

    access.grants.add("jobs:list");
    view.rerender(
      createElement(
        MantineProvider,
        { env: "test" },
        createElement(ConsoleNotifications),
        createElement(ChannelRuns, { channelId: "chn_1" }),
      ),
    );
    expect(screen.getByRole("button", { name: "channels.run.stop" })).toBeTruthy();
  });
});
