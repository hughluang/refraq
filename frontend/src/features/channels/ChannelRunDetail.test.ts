/** @vitest-environment jsdom */

import { MantineProvider } from "@mantine/core";
import { notifications, notificationsStore } from "@mantine/notifications";
import { act, cleanup, fireEvent, render, screen, within } from "@testing-library/react";
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
  listExecutions: vi.fn(),
}));

const bridges = vi.hoisted(() => ({
  canvas: null as null | {
    focusNodeId?: string | null;
    onRunNodeOpen?: (open: {
      nodeId: string;
      status: "none" | "ready" | "unfetched";
      execution?: { seq: number; node_id: string };
    }) => void;
    runNodeFocus?: { token: number; nodeId: string; pins: Record<string, number> } | null;
  },
  browser: null as null | {
    reloadToken?: number;
    selectionRequest?: { seq: number; token: number } | null;
    onExecutionSelect?: (execution: {
      seq: number;
      node_id: string;
      container_seq: number | null;
      round: number | null;
    }) => void;
  },
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
  getRun: (channelId: string, jobId: string, init?: { signal?: AbortSignal }) =>
    api.getRun(channelId, jobId, init),
  listNodeTypes: () => api.listNodeTypes(),
  rerunRun: (channelId: string, jobId: string) => api.rerunRun(channelId, jobId),
  listExecutions: (
    channelId: string,
    jobId: string,
    params?: { node_id?: string; limit?: number; offset?: number },
  ) => api.listExecutions(channelId, jobId, params),
}));

vi.mock("@/features/jobs/api", () => ({
  cancelJob: (jobId: string) => jobs.cancelJob(jobId),
}));

vi.mock("@/features/channels/ChannelCanvas", () => ({
  ChannelCanvas: (props: {
    focusNodeId?: string | null;
    onRunNodeOpen?: (open: {
      nodeId: string;
      status: "none" | "ready" | "unfetched";
      execution?: { seq: number; node_id: string };
    }) => void;
    runNodeFocus?: { token: number; nodeId: string; pins: Record<string, number> } | null;
  }) => {
    bridges.canvas = props;
    return createElement("div", { "data-testid": "run-detail-canvas" });
  },
}));

vi.mock("@/features/channels/RunExecutionBrowser", () => ({
  RunExecutionBrowser: (props: {
    reloadToken?: number;
    selectionRequest?: { seq: number; token: number } | null;
    onExecutionSelect?: (execution: {
      seq: number;
      node_id: string;
      container_seq: number | null;
      round: number | null;
    }) => void;
  }) => {
    bridges.browser = props;
    return createElement("div", {
      "data-testid": "execution-table",
      "data-reload-token": String(props.reloadToken ?? 0),
      "data-selection-seq": props.selectionRequest ? String(props.selectionRequest.seq) : "",
      "data-selection-token": props.selectionRequest ? String(props.selectionRequest.token) : "",
    });
  },
}));

vi.mock("@refinedev/core", () => ({
  useTranslate: () => (key: string, options?: Record<string, unknown>) => {
    const template =
      key === "status.freshness" ? "Last updated {{time}}" : (i18n.extra[key] ?? key);
    if (!options) return template;
    return template.replace(/\{\{(\w+)\}\}/g, (_, name: string) => String(options[name] ?? ""));
  },
  useNotification: () => ({ open: vi.fn() }),
  useCan: (request: { resource: string; action: string }) => ({
    data: { can: access.grants.has(`${request.resource}:${request.action}`) },
  }),
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
  useSearchParams: () => new URLSearchParams(window.location.search),
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

function run(status: string, jobId = "job_1"): ChannelRun {
  return {
    job_id: jobId,
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

function detail(
  status: string,
  summaries: RunDetail["node_summaries"] = [],
  jobId = "job_1",
): RunDetail {
  return { run: run(status, jobId), graph: EMPTY_GRAPH, node_summaries: summaries };
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

function detailElement(jobId = "job_1") {
  return createElement(
    MantineProvider,
    { env: "test" },
    createElement(ConsoleNotifications),
    createElement(ChannelRunDetail, { channelId: "chn_1", jobId }),
  );
}

function renderDetail() {
  return render(detailElement());
}

function politeRegion(): HTMLElement | null {
  return document.querySelector("[aria-live='polite']");
}

describe("ChannelRunDetail load feedback", () => {
  it.each(["queued", "cancelled"])("keeps %s graphless run inspectable", async (status) => {
    api.getRun.mockResolvedValue({ ...detail(status), graph: null });
    renderDetail();
    await advance(0);
    expect(screen.getByRole("heading", { name: "channels.runs.subject.version" })).toBeTruthy();
    expect(screen.queryByText("channels.title: chn_1")).toBeNull();
    expect(screen.getByText(status === "queued" ? "channels.runDetail.graphPending" : "channels.runDetail.graphUnavailable")).toBeTruthy();
    expect(screen.queryByTestId("run-detail-canvas")).toBeNull();
    expect(screen.getByRole("link", { name: "channels.runDetail.back" })).toBeTruthy();
  });
  beforeEach(() => {
    vi.useFakeTimers();
    vi.setSystemTime(new Date("2026-10-11T06:00:29Z"));
    stubDom();
    window.history.replaceState(null, "", "/console/channels/chn_1/runs/job_1");
    resetNotifications();
    i18n.extra = {};
    access.grants.clear();
    api.getRun.mockReset();
    api.listNodeTypes.mockReset();
    api.rerunRun.mockReset();
    api.listExecutions.mockReset();
    bridges.canvas = null;
    bridges.browser = null;
    jobs.cancelJob.mockReset();
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

  it("updates the return link when retained detail receives a new history context", async () => {
    api.getRun.mockResolvedValue(detail("succeeded"));
    const view = renderDetail();
    await advance(0);
    window.history.replaceState(null, "", "/console/channels/chn_1/runs/job_1?run_origin=edit&run_status=failed&run_target=draft&run_page=3");
    view.rerender(detailElement());
    expect(screen.getByRole("link", { name: "channels.runDetail.back" }).getAttribute("href")).toBe(
      "/console/channels/chn_1/edit?run_panel=runs&run_origin=edit&run_status=failed&run_target=draft&run_page=3",
    );
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
    expect(screen.queryByText(/jobs\.fields\.trigger/)).toBeNull();
  });

  it("hides an ordinary completion and keeps a partial stop", async () => {
    api.getRun.mockResolvedValue({
      ...detail("succeeded"),
      run: { ...run("succeeded"), outcome: "completed" },
    });
    const completed = renderDetail();
    await advance(0);
    expect(screen.queryByText("channels.runs.outcome.completed")).toBeNull();
    expect(screen.getAllByText("channels.runs.subject.version")).toHaveLength(1);
    completed.unmount();

    api.getRun.mockResolvedValue({
      ...detail("succeeded"),
      run: { ...run("succeeded"), outcome: "completed", stop_at_node_id: "write" },
      graph: {
        ...EMPTY_GRAPH,
        nodes: [{
          id: "write",
          ref: "write",
          type: "transform.count",
          name: "Count",
          position: { x: 0, y: 0 },
          config: {},
          on_error: "stop",
          retry: null,
        }],
      },
    });
    renderDetail();
    await advance(0);
    expect(screen.queryByText("channels.runs.outcome.completed")).toBeNull();
    expect(screen.getByText("channels.runs.partial")).toBeTruthy();
  });

  it("leaves a user run without an inbound label", async () => {
    api.getRun.mockResolvedValue(detail("succeeded"));
    renderDetail();

    await advance(0);
    expect(screen.queryByText(/channels\.runs\.trigger\.inbound/)).toBeNull();
    expect(screen.queryByText("user")).toBeNull();
  });

  it("fills the viewport and keeps the index and inspector beside the canvas", async () => {
    api.getRun.mockResolvedValue(detail("succeeded"));
    renderDetail();

    await advance(0);

    const scroll = document.querySelector("[data-page-scroll]") as HTMLElement;
    expect(scroll.style.overflow).toBe("hidden");

    const workspace = screen.getByTestId("run-detail-workspace");
    expect(workspace.getAttribute("data-arrangement")).toBeTruthy();
    expect(workspace.className).toContain("channel-run-workspace");
    const canvas = screen.getByTestId("run-detail-canvas");
    const table = screen.getByTestId("execution-table");
    const inspector = screen.getByTestId("run-detail-inspector");
    expect(workspace.contains(canvas)).toBe(true);
    expect(workspace.contains(table)).toBe(true);
    expect(canvas.contains(table)).toBe(false);
    expect(canvas.contains(inspector)).toBe(false);
    expect(canvas.parentElement?.className).toContain("channel-run-workspace__graph");
    expect(inspector.className).toContain("channel-run-workspace__inspector");
    expect(inspector.className).not.toContain("channel-node-config--detail");
    expect(canvas.parentElement?.getAttribute("style") ?? "").not.toContain("32dvh");
    expect(scroll.contains(workspace)).toBe(true);
    expect(workspace.getAttribute("data-index")).toBe("true");
    expect(workspace.getAttribute("data-inspector")).toBe("false");
  });

  it("reloads executions when a later poll changes the recorded run and not on the first load", async () => {
    const same = { node_id: "write", execution_count: 1, status_counts: { running: 1 } };
    api.getRun
      .mockResolvedValueOnce(detail("running", [same]))
      .mockResolvedValueOnce(detail("running", [{ ...same }]))
      .mockResolvedValueOnce(
        detail("running", [{ node_id: "write", execution_count: 2, status_counts: { running: 1 } }]),
      );
    renderDetail();

    await advance(0);
    expect(api.getRun).toHaveBeenCalledTimes(1);
    expect(screen.getByTestId("execution-table").getAttribute("data-reload-token")).toBe("0");

    await advance(LIVE_STATUS_INTERVAL_MS);
    expect(api.getRun).toHaveBeenCalledTimes(2);
    expect(screen.getByTestId("execution-table").getAttribute("data-reload-token")).toBe("0");

    await advance(LIVE_STATUS_INTERVAL_MS);
    expect(api.getRun).toHaveBeenCalledTimes(3);
    expect(screen.getByTestId("execution-table").getAttribute("data-reload-token")).toBe("1");
  });

  it("reloads executions when a later poll changes only the run status", async () => {
    api.getRun.mockResolvedValueOnce(detail("running")).mockResolvedValueOnce(detail("succeeded"));
    renderDetail();

    await advance(0);
    expect(screen.getByTestId("execution-table").getAttribute("data-reload-token")).toBe("0");

    await advance(LIVE_STATUS_INTERVAL_MS);
    expect(api.getRun).toHaveBeenCalledTimes(2);
    expect(screen.getByTestId("execution-table").getAttribute("data-reload-token")).toBe("1");
  });

  it("reloads executions when a later poll changes only a node status count", async () => {
    api.getRun
      .mockResolvedValueOnce(
        detail("running", [{ node_id: "write", execution_count: 1, status_counts: { running: 1 } }]),
      )
      .mockResolvedValueOnce(
        detail("running", [
          { node_id: "write", execution_count: 1, status_counts: { succeeded: 1 } },
        ]),
      );
    renderDetail();

    await advance(0);
    expect(screen.getByTestId("execution-table").getAttribute("data-reload-token")).toBe("0");

    await advance(LIVE_STATUS_INTERVAL_MS);
    expect(api.getRun).toHaveBeenCalledTimes(2);
    expect(screen.getByTestId("execution-table").getAttribute("data-reload-token")).toBe("1");
  });

  it("does not reload executions on the first getRun after the job changes", async () => {
    const running = { node_id: "write", execution_count: 1, status_counts: { running: 1 } };
    const later = { node_id: "write", execution_count: 2, status_counts: { running: 1 } };
    api.getRun
      .mockResolvedValueOnce(detail("running", [running], "job_1"))
      .mockResolvedValueOnce(detail("running", [later], "job_2"))
      .mockResolvedValueOnce(
        detail(
          "running",
          [{ node_id: "write", execution_count: 3, status_counts: { running: 1 } }],
          "job_2",
        ),
      );
    const view = renderDetail();
    const token = () => screen.getByTestId("execution-table").getAttribute("data-reload-token");

    await advance(0);
    expect(token()).toBe("0");

    view.rerender(detailElement("job_2"));
    await advance(0);
    expect(api.getRun).toHaveBeenCalledTimes(2);
    expect(api.getRun.mock.calls[1]?.[1]).toBe("job_2");
    expect(token()).toBe("0");

    await advance(LIVE_STATUS_INTERVAL_MS);
    expect(api.getRun).toHaveBeenCalledTimes(3);
    expect(token()).toBe("1");
  });

  it("does not reload executions when a later poll fails", async () => {
    api.getRun.mockResolvedValueOnce(detail("running")).mockRejectedValueOnce(new Error("offline"));
    renderDetail();

    await advance(0);
    await advance(LIVE_STATUS_INTERVAL_MS);
    expect(api.getRun).toHaveBeenCalledTimes(2);
    expect(screen.getByTestId("execution-table").getAttribute("data-reload-token")).toBe("0");
  });

  it("announces a later status in the polite live region", async () => {
    api.getRun.mockResolvedValueOnce(detail("running")).mockResolvedValue(detail("succeeded"));
    renderDetail();

    await advance(0);
    expect(politeRegion()?.textContent).toBe("");

    await advance(LIVE_STATUS_INTERVAL_MS);
    expect(politeRegion()?.textContent).toBe("status.job.succeeded");
  });

  it("stops this run from the header by its start time", async () => {
    access.grants.add("channels:edit");
    i18n.extra["channels.run.stop.confirmTitle"] = "Stop {{name}}?";
    i18n.extra["feedback.confirm.body"] = "{{record}}: {{consequence}}";
    const running = detail("running");
    running.run = {
      ...running.run,
      created_at: "2026-10-11T05:00:00Z",
      started_at: "2026-10-11T06:00:29Z",
    };
    api.getRun.mockResolvedValue(running);
    renderDetail();

    await advance(0);
    fireEvent.click(screen.getByRole("button", { name: "channels.run.stop" }));
    const dialog = screen.getByRole("dialog", { name: "Stop 10/11/2026, 6:00:29 AM?" });
    const shown = "10/11/2026, 6:00:29 AM";
    expect(dialog.textContent?.split(shown).length).toBe(3);
    expect(dialog.textContent).not.toContain("10/11/2026, 5:00:00 AM");
    expect(screen.getByRole("link", { name: "channels.runDetail.back" }).getAttribute("href")).toBe(
      "/console/channels/chn_1?run_panel=runs",
    );
  });

  it("names a queued run by its created time in the stop confirmation", async () => {
    access.grants.add("channels:edit");
    i18n.extra["channels.run.stop.confirmTitle"] = "Stop {{name}}?";
    const queued = detail("queued");
    queued.run = {
      ...queued.run,
      created_at: "2026-10-11T05:00:00Z",
      started_at: null,
    };
    api.getRun.mockResolvedValue(queued);
    renderDetail();

    await advance(0);
    fireEvent.click(screen.getByRole("button", { name: "channels.run.stop" }));
    expect(screen.getByRole("dialog", { name: "Stop 10/11/2026, 5:00:00 AM?" })).toBeTruthy();
  });

  it("cancels this page's job from the header and reloads the run before the next poll", async () => {
    access.grants.add("channels:edit");
    i18n.extra["channels.run.stop.confirmTitle"] = "Stop {{name}}?";
    api.getRun.mockResolvedValue(detail("running", [], "job_page"));
    jobs.cancelJob.mockResolvedValue({ job: { id: "job_page" } });
    render(detailElement("job_page"));

    await advance(0);
    expect(api.getRun).toHaveBeenCalledTimes(1);
    expect(api.getRun.mock.calls[0]?.[1]).toBe("job_page");
    fireEvent.click(screen.getByRole("button", { name: "channels.run.stop" }));
    fireEvent.click(
      within(screen.getByRole("dialog", { name: "Stop 10/11/2026, 6:00:29 AM?" })).getByRole(
        "button",
        { name: "channels.run.stop" },
      ),
    );
    await advance(0);

    expect(jobs.cancelJob).toHaveBeenCalledTimes(1);
    expect(jobs.cancelJob).toHaveBeenCalledWith("job_page");
    expect(api.getRun).toHaveBeenCalledTimes(2);
    expect(screen.getByTestId("execution-table").getAttribute("data-reload-token")).toBe("0");
  });

  it("offers header Stop when the caller can list jobs, and hides it when they can do neither", async () => {
    api.getRun.mockResolvedValue(detail("queued"));
    const view = renderDetail();
    await advance(0);
    expect(screen.queryByRole("button", { name: "channels.run.stop" })).toBeNull();

    access.grants.add("jobs:list");
    view.rerender(detailElement());
    expect(screen.getByRole("button", { name: "channels.run.stop" })).toBeTruthy();
    expect(screen.queryByRole("button", { name: "channels.runDetail.rerun" })).toBeNull();
  });

  it("hides header Stop once the run has ended", async () => {
    access.grants.add("channels:edit");
    for (const status of ["succeeded", "cancelled"]) {
      api.getRun.mockResolvedValue(detail(status));
      const view = renderDetail();
      await advance(0);
      expect(screen.queryByRole("button", { name: "channels.run.stop" })).toBeNull();
      view.unmount();
    }
    api.getRun.mockResolvedValue(detail("failed"));
    renderDetail();
    await advance(0);
    expect(screen.queryByRole("button", { name: "channels.run.stop" })).toBeNull();
    expect(screen.getByRole("button", { name: "channels.runDetail.rerun" })).toBeTruthy();
  });

  it("does not offer rerun without a resolved published version", async () => {
    access.grants.add("channels:edit");
    const body = detail("failed");
    body.run.version = null;
    body.graph = null;
    api.getRun.mockResolvedValue(body);
    renderDetail();
    await advance(0);
    expect(screen.queryByRole("button", { name: "channels.runDetail.rerun" })).toBeNull();
    expect(screen.getByRole("heading", { name: "job_1" })).toBeTruthy();
  });

  it("reruns a failed published run on one click", async () => {
    access.grants.add("channels:edit");
    api.getRun.mockResolvedValue(detail("failed"));
    api.rerunRun.mockReturnValue(new Promise(() => undefined));
    renderDetail();
    await advance(0);

    fireEvent.click(screen.getByRole("button", { name: "channels.runDetail.rerun" }));
    await advance(0);
    expect(api.rerunRun).toHaveBeenCalledTimes(1);
    expect(api.rerunRun).toHaveBeenCalledWith("chn_1", "job_1");
    expect(screen.queryByRole("dialog")).toBeNull();
    expect(jobs.cancelJob).not.toHaveBeenCalled();
  });

  it("selects the latest execution when a run-detail node opens and leaves the table when that node has none", async () => {
    const body = detail("failed", [
      { node_id: "write", execution_count: 3, status_counts: { failed: 1 } },
    ]);
    body.run.failed_node_id = "write";
    api.getRun.mockResolvedValue(body);
    api.listExecutions.mockResolvedValue({
      items: [{ seq: 80, node_id: "write" }],
      total: 80,
      limit: 1,
      offset: 2,
    });
    renderDetail();
    await advance(0);

    expect(bridges.canvas?.focusNodeId).toBe("write");
    await act(async () => {
      bridges.canvas?.onRunNodeOpen?.({ nodeId: "write", status: "unfetched" });
    });
    await advance(0);

    expect(api.listExecutions).toHaveBeenCalledWith("chn_1", "job_1", {
      node_id: "write",
      limit: 1,
      offset: 2,
    });
    const table = screen.getByTestId("execution-table");
    expect(table.getAttribute("data-selection-seq")).toBe("80");
    expect(table.getAttribute("data-selection-token")).toBe("1");

    await act(async () => {
      bridges.canvas?.onRunNodeOpen?.({
        nodeId: "idle",
        status: "ready",
        execution: { seq: 4, node_id: "idle" },
      });
    });
    expect(table.getAttribute("data-selection-seq")).toBe("4");

    await act(async () => {
      bridges.canvas?.onRunNodeOpen?.({ nodeId: "idle", status: "none" });
    });
    expect(table.getAttribute("data-selection-seq")).toBe("4");
    expect(table.getAttribute("data-selection-token")).toBe("2");
  });

  it("does not move the selected execution when a later poll changes the summary", async () => {
    api.getRun
      .mockResolvedValueOnce(
        detail("running", [
          { node_id: "write", execution_count: 1, status_counts: { running: 1 } },
        ]),
      )
      .mockResolvedValueOnce(
        detail("running", [
          { node_id: "write", execution_count: 2, status_counts: { running: 1, succeeded: 1 } },
        ]),
      );
    renderDetail();
    await advance(0);
    await act(async () => {
      bridges.canvas?.onRunNodeOpen?.({
        nodeId: "write",
        status: "ready",
        execution: { seq: 80, node_id: "write" },
      });
    });
    expect(screen.getByTestId("execution-table").getAttribute("data-selection-seq")).toBe("80");
    expect(api.listExecutions).not.toHaveBeenCalled();

    await advance(LIVE_STATUS_INTERVAL_MS);
    const table = screen.getByTestId("execution-table");
    expect(table.getAttribute("data-reload-token")).toBe("1");
    expect(table.getAttribute("data-selection-seq")).toBe("80");
    expect(table.getAttribute("data-selection-token")).toBe("1");
    expect(api.listExecutions).not.toHaveBeenCalled();
  });

  it("opens the clicked execution's node and pins rounds from its container chain", async () => {
    api.getRun.mockResolvedValue(detail("succeeded"));
    api.listExecutions.mockImplementation(async (_channelId, _jobId, params) => {
      if (params?.offset === 9) {
        return {
          items: [{ seq: 10, node_id: "for_1", container_seq: 3, round: 1 }],
          total: 12,
          limit: 1,
          offset: 9,
        };
      }
      if (params?.offset === 2) {
        return {
          items: [{ seq: 3, node_id: "batch_1", container_seq: null, round: null }],
          total: 12,
          limit: 1,
          offset: 2,
        };
      }
      return { items: [], total: 0, limit: 1, offset: params?.offset ?? 0 };
    });
    renderDetail();
    await advance(0);

    await act(async () => {
      bridges.browser?.onExecutionSelect?.({
        seq: 12,
        node_id: "step",
        container_seq: 10,
        round: 2,
      });
    });
    await advance(0);

    expect(api.listExecutions).toHaveBeenCalledWith("chn_1", "job_1", { limit: 1, offset: 9 });
    expect(api.listExecutions).toHaveBeenCalledWith("chn_1", "job_1", { limit: 1, offset: 2 });
    expect(bridges.canvas?.runNodeFocus).toEqual({
      token: 1,
      nodeId: "step",
      pins: { batch_1: 1, for_1: 2 },
    });
  });

  it("stops the container walk when the execution at that offset is a different seq", async () => {
    api.getRun.mockResolvedValue(detail("succeeded"));
    api.listExecutions.mockResolvedValue({
      items: [{ seq: 99, node_id: "other", container_seq: 3, round: 1 }],
      total: 99,
      limit: 1,
      offset: 9,
    });
    renderDetail();
    await advance(0);

    await act(async () => {
      bridges.browser?.onExecutionSelect?.({
        seq: 12,
        node_id: "step",
        container_seq: 10,
        round: 2,
      });
    });
    await advance(0);

    expect(api.listExecutions).toHaveBeenCalledTimes(1);
    expect(api.listExecutions).toHaveBeenCalledWith("chn_1", "job_1", { limit: 1, offset: 9 });
    expect(bridges.canvas?.runNodeFocus).toEqual({ token: 1, nodeId: "step", pins: {} });
  });

  it("keeps a clicked execution when a slower latest-execution read returns", async () => {
    api.getRun.mockResolvedValue(
      detail("running", [{ node_id: "write", execution_count: 2, status_counts: { running: 1 } }]),
    );
    let resolveLatest: (value: unknown) => void = () => {};
    api.listExecutions.mockImplementation(
      () =>
        new Promise((resolve) => {
          resolveLatest = resolve;
        }),
    );
    renderDetail();
    await advance(0);

    await act(async () => {
      bridges.canvas?.onRunNodeOpen?.({ nodeId: "write", status: "unfetched" });
    });
    await act(async () => {
      bridges.browser?.onExecutionSelect?.({
        seq: 4,
        node_id: "step",
        container_seq: null,
        round: null,
      });
    });
    await advance(0);
    expect(bridges.canvas?.runNodeFocus).toEqual({ token: 1, nodeId: "step", pins: {} });

    await act(async () => {
      resolveLatest({
        items: [{ seq: 99, node_id: "write" }],
        total: 2,
        limit: 1,
        offset: 1,
      });
    });
    await advance(0);
    expect(screen.getByTestId("execution-table").getAttribute("data-selection-seq")).toBe("");
    expect(bridges.canvas?.runNodeFocus).toEqual({ token: 1, nodeId: "step", pins: {} });
  });
});
