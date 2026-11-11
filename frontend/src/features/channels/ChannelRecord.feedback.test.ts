/** @vitest-environment jsdom */

import { MantineProvider } from "@mantine/core";
import { notifications, notificationsStore } from "@mantine/notifications";
import { act, cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { createElement, type ReactNode } from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import {
  createChannel,
  getChannel,
  getDraft,
  getRun,
  listNodeTypes,
  listRuns,
  patchChannel,
  validateDraft,
} from "@/features/channels/api";
import {
  EMPTY_GRAPH,
  type Channel,
  type ChannelRunDetail,
  type Graph,
  type NodeTypeSpec,
} from "@/features/channels/types";
import { LIVE_STATUS_INTERVAL_MS } from "@/hooks/useLiveStatus";
import { ApiError } from "@/lib/api";
import { bindClientI18n } from "@/providers/i18n-runtime";
import { ConsoleNotifications } from "@/providers/notification-provider";
import {
  resetSessionStoreForTests,
  useSessionStore,
  type CurrentUser,
} from "@/providers/session-store";

vi.mock("@refinedev/core", () => ({
  matchResourceFromRoute: () => ({ found: false }),
  useTranslate: () => (key: string, options?: Record<string, unknown>) => {
    const template = key === "status.freshness" ? "Last updated {{time}}" : key;
    if (!options) return template;
    return template.replace(/\{\{(\w+)\}\}/g, (_, name: string) => String(options[name] ?? ""));
  },
  useNotification: () => ({ open: vi.fn() }),
  useCan: () => ({ data: { can: true } }),
  usePermissions: () => ({ data: [] as string[] }),
  useBreadcrumb: () => ({ breadcrumbs: [] }),
}));

vi.mock("next/link", () => ({
  default: ({ href, children }: { href: string; children?: ReactNode }) =>
    createElement("a", { href }, children),
  useLinkStatus: () => ({ pending: false }),
}));

vi.mock("next/navigation", () => ({
  usePathname: () => "/console/channels",
  useRouter: () => ({ push: vi.fn(), replace: vi.fn(), refresh: vi.fn() }),
  useSearchParams: () => new URLSearchParams(),
}));

vi.mock("@/features/channels/api", () => ({
  activateChannel: vi.fn(),
  createChannel: vi.fn(),
  deactivateChannel: vi.fn(),
  deleteChannel: vi.fn(),
  getChannel: vi.fn(),
  getDraft: vi.fn(),
  getRun: vi.fn(),
  getVersion: vi.fn(),
  listChannels: vi.fn(),
  listNodeTypes: vi.fn(),
  listRuns: vi.fn(),
  patchChannel: vi.fn(),
  previewPublish: vi.fn(),
  previewTemplate: vi.fn(),
  publishChannel: vi.fn(),
  saveDraft: vi.fn(),
  startRun: vi.fn(),
  validateDraft: vi.fn(),
}));

vi.mock("@/features/jobs/api", () => ({
  cancelJob: vi.fn(),
}));

vi.mock("@/features/branding/BrandingProvider", () => ({
  useBranding: () => ({ brandName: "Refraq" }),
}));

const now = "2026-01-01T00:00:00Z";

const spec: NodeTypeSpec = {
  type: "manual",
  family: "trigger",
  label: "Manual",
  summary: "Start here",
  description: "",
  trigger: true,
  container: null,
  inputs: [],
  outputs: [{ port: "out", description: "" }],
  config_schema: {},
  permission: null,
};

function channel(): Channel {
  return {
    id: "chn_1",
    name: "Intake",
    description: null,
    active: false,
    draft_revision: 1,
    draft_updated_at: now,
    latest_version: null,
    failure_streak: 0,
    persistently_failing: false,
    tags: [],
    tag_revision: 1,
    created_at: now,
    updated_at: now,
  };
}

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
  if (!document.fonts) {
    Object.defineProperty(document, "fonts", {
      configurable: true,
      value: { addEventListener() {}, removeEventListener() {} },
    });
  }
  if (!SVGElement.prototype.getBBox) {
    SVGElement.prototype.getBBox = () => ({
      x: 0,
      y: 0,
      width: 0,
      height: 0,
      bottom: 0,
      left: 0,
      right: 0,
      top: 0,
      toJSON: () => ({}),
    });
  }
}

function readyRecord() {
  vi.mocked(getChannel).mockResolvedValue({ channel: channel() });
  vi.mocked(getDraft).mockResolvedValue({
    draft_revision: 1,
    draft_updated_at: now,
    graph: EMPTY_GRAPH,
  });
  vi.mocked(listNodeTypes).mockResolvedValue({ items: [spec] });
  vi.mocked(listRuns).mockResolvedValue({ items: [], total: 0, limit: 1, offset: 0 });
  vi.mocked(validateDraft).mockResolvedValue({
    valid: true,
    problems: [],
    ports: [],
    context: { channel: {}, run: {}, platform: {} },
  });
}

function resetNotifications() {
  const state = notificationsStore.getState();
  for (const item of [...state.notifications, ...state.queue]) {
    notifications.hide(item.id);
  }
  notifications.clean();
}

function shell(node: ReactNode) {
  return createElement(
    MantineProvider,
    { env: "test" },
    createElement(ConsoleNotifications),
    node,
  );
}

function rejected(requestId: string) {
  return new ApiError(500, "NO_SUCH_CODE", "Raw English detail", requestId);
}

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

function runningDetail(): ChannelRunDetail {
  return {
    run: {
      job_id: "job_1",
      status: "running",
      outcome: null,
      target: "draft",
      version: null,
      draft_revision: 1,
      trigger_kind: "user",
      trigger_ref: "manual",
      trigger_node_id: "nd_1",
      trigger_actor_name: null,
      trigger_schedule_name: null,
      ignore_checkpoints: false,
      stop_at_node_id: null,
      failed_node_id: null,
      created_at: now,
      started_at: now,
      finished_at: null,
      error_code: null,
      error_message: null,
    },
    graph: EMPTY_GRAPH,
    node_summaries: [],
  };
}

function stubTimeZones() {
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

describe("ChannelRecord feedback", () => {
  beforeEach(() => {
    stubDomApis();
    vi.mocked(createChannel).mockReset();
    vi.mocked(getChannel).mockReset();
    vi.mocked(getDraft).mockReset();
    vi.mocked(getRun).mockReset();
    vi.mocked(listNodeTypes).mockReset();
    vi.mocked(listRuns).mockReset();
    vi.mocked(patchChannel).mockReset();
    vi.mocked(validateDraft).mockReset();
    resetNotifications();
  });

  afterEach(() => {
    cleanup();
    resetNotifications();
    vi.unstubAllGlobals();
    resetSessionStoreForTests();
    bindClientI18n({ t: (key: string) => key } as never);
    vi.useRealTimers();
  });

  it("shows one error notification and no form alert when create is rejected", async () => {
    vi.mocked(createChannel).mockRejectedValue(rejected("req-create"));
    const { ChannelRecord } = await import("@/features/channels/ChannelRecord");
    render(shell(createElement(ChannelRecord, { mode: "create" })));

    fireEvent.change(screen.getByRole("textbox", { name: /channels\.fields\.name/ }), {
      target: { value: "Intake" },
    });
    fireEvent.submit(document.getElementById("channel-record-form") as HTMLFormElement);

    const alerts = await screen.findAllByRole("alert");
    expect(alerts).toHaveLength(1);
    const form = document.getElementById("channel-record-form");
    expect(form?.querySelector("[role='alert']")).toBeNull();
    expect(alerts[0]?.textContent).toContain("problems.unknown");
    expect(alerts[0]?.textContent).toContain("common.requestId");
    expect(alerts[0]?.textContent).toContain("req-create");
    expect(screen.queryByRole("button", { name: "common.retry" })).toBeNull();
  });

  it("shows one error notification and no form alert when the edit save is rejected", async () => {
    readyRecord();
    vi.mocked(patchChannel).mockRejectedValue(rejected("req-edit"));
    const { ChannelRecord } = await import("@/features/channels/ChannelRecord");
    render(shell(createElement(ChannelRecord, { mode: "edit", channelId: "chn_1" })));

    fireEvent.click(await screen.findByRole("button", { name: "Intake" }));
    const name = screen.getByRole("textbox", { name: /channels\.fields\.name/ });
    fireEvent.change(name, { target: { value: "Intake west" } });
    fireEvent.blur(name);
    fireEvent.click(screen.getByRole("button", { name: "channels.edit.submit" }));

    const alerts = await screen.findAllByRole("alert");
    expect(alerts).toHaveLength(1);
    const scroll = document.querySelector("[data-page-scroll]");
    expect(scroll?.querySelector("[role='alert']")).toBeNull();
    expect(alerts[0]?.textContent).toContain("problems.unknown");
    expect(alerts[0]?.textContent).toContain("req-edit");
    expect(screen.queryByRole("button", { name: "common.retry" })).toBeNull();
    await waitFor(() => {
      expect(patchChannel).toHaveBeenCalledTimes(1);
    });
  });

  it("keeps the header, shows unloaded, and retries a failed load from the notification", async () => {
    vi.mocked(getChannel).mockRejectedValueOnce(rejected("req-load"));
    vi.mocked(getChannel).mockResolvedValue({ channel: channel() });
    vi.mocked(getDraft).mockResolvedValue({
      draft_revision: 1,
      draft_updated_at: now,
      graph: EMPTY_GRAPH,
    });
    vi.mocked(listNodeTypes).mockResolvedValue({ items: [spec] });
    vi.mocked(listRuns).mockResolvedValue({ items: [], total: 0, limit: 1, offset: 0 });
    vi.mocked(validateDraft).mockResolvedValue({
      valid: true,
      problems: [],
      ports: [],
      context: { channel: {}, run: {}, platform: {} },
    });
    const { ChannelRecord } = await import("@/features/channels/ChannelRecord");
    render(shell(createElement(ChannelRecord, { mode: "show", channelId: "chn_1" })));

    const heading = await screen.findByRole("heading", { name: "channels.title" });
    expect(document.querySelector("[data-page-header]")?.contains(heading)).toBe(true);
    const status = screen.getByRole("button", { name: "status.unloaded" });
    const scroll = document.querySelector("[data-page-scroll]");
    expect(scroll?.contains(status)).toBe(true);
    expect(scroll?.querySelector("[role='alert']")).toBeNull();
    expect(screen.queryByRole("heading", { name: "layout.notFound.title" })).toBeNull();
    const alerts = screen.getAllByRole("alert");
    expect(alerts).toHaveLength(1);
    expect(alerts[0]?.textContent).toContain("problems.unknown");
    expect(alerts[0]?.textContent).toContain("req-load");

    fireEvent.click(screen.getByRole("button", { name: "common.retry" }));
    expect(await screen.findByRole("heading", { name: "Intake" })).toBeTruthy();
    expect(screen.queryByRole("button", { name: "status.unloaded" })).toBeNull();
    expect(getChannel).toHaveBeenCalledTimes(2);
  });

  it("shows unloaded, not a missing record, when the load is rejected with HTTP 404", async () => {
    vi.mocked(getChannel).mockRejectedValue(
      new ApiError(404, "CHANNEL_NOT_FOUND", "missing", "req-404"),
    );
    vi.mocked(getDraft).mockResolvedValue({
      draft_revision: 1,
      draft_updated_at: now,
      graph: EMPTY_GRAPH,
    });
    vi.mocked(listNodeTypes).mockResolvedValue({ items: [spec] });
    vi.mocked(listRuns).mockResolvedValue({ items: [], total: 0, limit: 1, offset: 0 });
    const { ChannelRecord } = await import("@/features/channels/ChannelRecord");
    render(shell(createElement(ChannelRecord, { mode: "show", channelId: "chn_1" })));

    expect(await screen.findByRole("button", { name: "status.unloaded" })).toBeTruthy();
    expect(screen.queryByRole("heading", { name: "layout.notFound.title" })).toBeNull();
    expect(screen.getAllByRole("alert")).toHaveLength(1);
    expect(screen.getByRole("alert").textContent).toContain("req-404");
  });

  it("shows unloaded, not a missing record, when the load throws a non-API error", async () => {
    vi.mocked(getChannel).mockRejectedValue(new Error("socket hang up"));
    vi.mocked(getDraft).mockResolvedValue({
      draft_revision: 1,
      draft_updated_at: now,
      graph: EMPTY_GRAPH,
    });
    vi.mocked(listNodeTypes).mockResolvedValue({ items: [spec] });
    vi.mocked(listRuns).mockResolvedValue({ items: [], total: 0, limit: 1, offset: 0 });
    const { ChannelRecord } = await import("@/features/channels/ChannelRecord");
    render(shell(createElement(ChannelRecord, { mode: "show", channelId: "chn_1" })));

    expect(await screen.findByRole("button", { name: "status.unloaded" })).toBeTruthy();
    expect(screen.queryByRole("heading", { name: "layout.notFound.title" })).toBeNull();
    expect(screen.getAllByRole("alert")).toHaveLength(1);
    expect(screen.getByRole("alert").textContent).toContain("problems.unknown");
  });

  it("shows not found, not the channel already on screen, when a later load resolves without a record", async () => {
    readyRecord();
    const { ChannelRecord } = await import("@/features/channels/ChannelRecord");
    const view = render(shell(createElement(ChannelRecord, { mode: "show", channelId: "chn_1" })));
    expect(await screen.findByRole("heading", { name: "Intake" })).toBeTruthy();

    vi.mocked(getChannel).mockResolvedValue({ channel: null as unknown as Channel });
    view.rerender(shell(createElement(ChannelRecord, { mode: "show", channelId: "chn_2" })));

    expect(await screen.findByRole("heading", { name: "layout.notFound.title" })).toBeTruthy();
    expect(screen.queryByRole("heading", { name: "Intake" })).toBeNull();
    expect(screen.queryByRole("button", { name: "status.unloaded" })).toBeNull();
    expect(screen.queryAllByRole("alert")).toHaveLength(0);
  });

  it("shows not found, not the channel already on screen, when a later load resolves without a graph", async () => {
    readyRecord();
    const { ChannelRecord } = await import("@/features/channels/ChannelRecord");
    const view = render(shell(createElement(ChannelRecord, { mode: "show", channelId: "chn_1" })));
    expect(await screen.findByRole("heading", { name: "Intake" })).toBeTruthy();

    vi.mocked(getDraft).mockResolvedValue({
      draft_revision: 1,
      draft_updated_at: now,
      graph: null as unknown as Graph,
    });
    view.rerender(shell(createElement(ChannelRecord, { mode: "show", channelId: "chn_2" })));

    expect(await screen.findByRole("heading", { name: "layout.notFound.title" })).toBeTruthy();
    expect(screen.queryByRole("heading", { name: "Intake" })).toBeNull();
    expect(screen.queryByRole("button", { name: "status.unloaded" })).toBeNull();
    expect(screen.queryAllByRole("alert")).toHaveLength(0);
  });

  it("shows not found when the load resolves without a record", async () => {
    vi.mocked(getChannel).mockResolvedValue({ channel: null as unknown as Channel });
    vi.mocked(getDraft).mockResolvedValue({
      draft_revision: 1,
      draft_updated_at: now,
      graph: EMPTY_GRAPH,
    });
    vi.mocked(listNodeTypes).mockResolvedValue({ items: [spec] });
    vi.mocked(listRuns).mockResolvedValue({ items: [], total: 0, limit: 1, offset: 0 });
    const { ChannelRecord } = await import("@/features/channels/ChannelRecord");
    render(shell(createElement(ChannelRecord, { mode: "show", channelId: "chn_1" })));

    expect(await screen.findByRole("heading", { name: "layout.notFound.title" })).toBeTruthy();
    expect(screen.queryByRole("button", { name: "status.unloaded" })).toBeNull();
    expect(screen.queryAllByRole("alert")).toHaveLength(0);
  });

  it("omits the run status badge after the latest draft run has ended", async () => {
    vi.useFakeTimers();
    readyRecord();
    const ended = runningDetail();
    ended.run.status = "succeeded";
    vi.mocked(listRuns).mockResolvedValue({
      items: [ended.run],
      total: 1,
      limit: 1,
      offset: 0,
    });
    vi.mocked(getRun).mockResolvedValue(ended);
    const { ChannelRecord } = await import("@/features/channels/ChannelRecord");
    render(shell(createElement(ChannelRecord, { mode: "show", channelId: "chn_1" })));

    await advance(0);
    expect(getRun).toHaveBeenCalled();
    expect(screen.getByRole("heading", { name: "Intake" })).toBeTruthy();
    expect(screen.queryByText("status.job.succeeded")).toBeNull();
  });

  it("marks a stale run with the last update, refreshes on click, and stays quiet on a background tick", async () => {
    vi.useFakeTimers();
    vi.setSystemTime(new Date("2026-10-11T06:00:29Z"));
    stubTimeZones();
    useSessionStore.setState({
      user: viewer,
      permissionsReady: true,
      identityError: null,
      signedOutLocally: false,
    });
    readyRecord();
    vi.mocked(listRuns).mockResolvedValue({
      items: [runningDetail().run],
      total: 1,
      limit: 1,
      offset: 0,
    });
    vi.mocked(getRun)
      .mockResolvedValueOnce(runningDetail())
      .mockResolvedValueOnce(runningDetail())
      .mockRejectedValueOnce(new Error("offline"))
      .mockResolvedValue(runningDetail());
    const { ChannelRecord } = await import("@/features/channels/ChannelRecord");
    render(shell(createElement(ChannelRecord, { mode: "show", channelId: "chn_1" })));

    await advance(0);
    expect(screen.getByText("status.job.running")).toBeTruthy();
    expect(screen.queryByRole("button", { name: UPDATED })).toBeNull();
    expect(screen.queryByText("liveStatus.stale")).toBeNull();
    expect(screen.queryAllByRole("alert")).toHaveLength(0);
    const header = document.querySelector("[data-page-header]");
    expect(header?.textContent).toContain("channels.status.inactive");
    expect(header?.textContent).not.toContain("status.job.running");

    await advance(LIVE_STATUS_INTERVAL_MS);
    const marker = screen.getByRole("button", { name: UPDATED });
    expect(header?.contains(marker)).toBe(false);
    expect(document.querySelector("[data-page-scroll]")?.contains(marker)).toBe(true);
    fireEvent.mouseEnter(marker);
    expect(screen.getByRole("tooltip").textContent).toBe(UPDATED);
    expect(screen.queryByText("liveStatus.stale")).toBeNull();
    expect(screen.queryByText("liveStatus.unavailable")).toBeNull();
    expect(screen.queryAllByRole("alert")).toHaveLength(0);

    fireEvent.click(marker);
    await advance(0);
    expect(screen.queryByRole("button", { name: UPDATED })).toBeNull();
    expect(screen.getByText("status.job.running")).toBeTruthy();
    expect(screen.queryAllByRole("alert")).toHaveLength(0);
  });

  it("notifies when refreshing the run from the freshness marker fails, and not on the next poll", async () => {
    bindClientI18n({
      t: (key: string) => (key === "feedback.repeated" ? "Repeated {{count}} times" : key),
    } as never);
    vi.useFakeTimers();
    vi.setSystemTime(new Date("2026-10-11T06:00:29Z"));
    stubTimeZones();
    useSessionStore.setState({
      user: viewer,
      permissionsReady: true,
      identityError: null,
      signedOutLocally: false,
    });
    readyRecord();
    vi.mocked(listRuns).mockResolvedValue({
      items: [runningDetail().run],
      total: 1,
      limit: 1,
      offset: 0,
    });
    vi.mocked(getRun)
      .mockResolvedValueOnce(runningDetail())
      .mockResolvedValueOnce(runningDetail())
      .mockImplementation(() =>
        Promise.reject(new ApiError(500, "NO_SUCH_CODE", "upstream timed out", "req-2")),
      );
    const { ChannelRecord } = await import("@/features/channels/ChannelRecord");
    render(shell(createElement(ChannelRecord, { mode: "show", channelId: "chn_1" })));

    await advance(0);
    await advance(LIVE_STATUS_INTERVAL_MS);
    expect(screen.getByRole("button", { name: UPDATED })).toBeTruthy();
    expect(screen.queryAllByRole("alert")).toHaveLength(0);

    fireEvent.click(screen.getByRole("button", { name: UPDATED }));
    await advance(0);
    expect(screen.getAllByRole("alert")).toHaveLength(1);
    expect(screen.getByText("problems.unknown")).toBeTruthy();
    expect(screen.getByRole("alert").textContent).toContain("req-2");

    await advance(LIVE_STATUS_INTERVAL_MS);
    expect(screen.getAllByRole("alert")).toHaveLength(1);
    expect(screen.queryByText("problems.unknown Repeated 2 times")).toBeNull();
  });
});
