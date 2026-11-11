/** @vitest-environment jsdom */

import { MantineProvider } from "@mantine/core";
import { act, cleanup, fireEvent, render, screen, within } from "@testing-library/react";
import { createElement, type ReactNode } from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import {
  getChannel,
  getDraft,
  getRun,
  getVersion,
  listChannels,
  listInboundRejections,
  listNodeTypes,
  listRuns,
  saveDraft,
  validateDraft,
  type InboundRejection,
} from "@/features/channels/api";
import { EMPTY_GRAPH, type Channel, type Graph, type NodeTypeSpec } from "@/features/channels/types";
import en from "@/locales/en-US/common.json";
import zh from "@/locales/zh-CN/common.json";

const LABELS: Record<string, string> = {
  "channels.tabs.rejections": "Rejections",
  "channels.rejections.refusedOnly": "This list is refused requests only.",
  "channels.rejections.empty": "No refused requests",
  "channels.rejections.hitCount": "Deduplication hits: {{count}}",
  "channels.rejections.reason.inactive": "Channel inactive",
  "channels.rejections.reason.busy": "In-flight cap reached",
  "channels.rejections.reason.unauthenticated": "Unauthenticated",
};

vi.mock("@refinedev/core", () => ({
  matchResourceFromRoute: () => ({ found: false }),
  useTranslate: () => (key: string, options?: Record<string, unknown>) => {
    const template = LABELS[key] ?? key;
    if (!options) return template;
    return template.replace(/\{\{(\w+)\}\}/g, (_, name: string) => String(options[name] ?? ""));
  },
  useNotification: () => ({ open: vi.fn() }),
  useCan: () => ({ data: { can: true } }),
  usePermissions: () => ({ data: [] as string[] }),
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
  listInboundRejections: vi.fn(),
  listNodeTypes: vi.fn(),
  listRuns: vi.fn(),
  patchChannel: vi.fn(),
  previewPublish: vi.fn(),
  previewTemplate: vi.fn(),
  publishChannel: vi.fn(),
  replaceChannelTags: vi.fn(),
  saveDraft: vi.fn(),
  startRun: vi.fn(),
  validateDraft: vi.fn(),
}));

vi.mock("@/features/tags/api", () => ({
  listTags: vi.fn(async () => ({ items: [], total: 0, limit: 8, offset: 0 })),
}));

vi.mock("@/features/jobs/api", () => ({
  cancelJob: vi.fn(),
}));

vi.mock("@/features/branding/BrandingProvider", () => ({
  useBranding: () => ({ brandName: "Refraq" }),
}));

vi.mock("@/features/inbound-credentials/api", () => ({
  listInboundCredentials: vi.fn(async () => ({ items: [], total: 0, limit: 200, offset: 0 })),
  getInboundCredential: vi.fn(async () => {
    throw new Error("missing");
  }),
}));

const now = "2026-01-01T00:00:00Z";

const spec: NodeTypeSpec = {
  type: "trigger.inbound",
  family: "trigger",
  label: "Inbound",
  summary: "Starts a run when a third party calls the published path.",
  description: "",
  trigger: true,
  container: null,
  inputs: [],
  outputs: [{ port: "main", description: "" }],
  config_schema: { type: "object", properties: {} },
  permission: null,
};

function channel(): Channel {
  return {
    id: "chn_1",
    name: "Intake",
    description: null,
    active: true,
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

function inboundGraph(): Graph {
  return {
    nodes: [
      {
        id: "nd_in",
        ref: "in",
        type: "trigger.inbound",
        name: "In",
        position: { x: 40, y: 40 },
        config: { path: "payments/callback" },
        on_error: "stop",
        retry: null,
      },
    ],
    edges: [],
    settings: EMPTY_GRAPH.settings,
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

function rejection(id: string, receivedAt: string, reason: string): InboundRejection {
  return {
    id,
    channel_id: "chn_1",
    node_id: "nd_in",
    path: "payments/callback",
    received_at: receivedAt,
    reason,
    method: "PATCH",
    headers: { "x-token": "secret-header-value" },
    query: { token: "secret-query-value" },
    body: "secret-body-value",
  };
}

function manualGraph(): Graph {
  return {
    nodes: [
      {
        id: "nd_1",
        ref: "run_manually",
        type: "trigger.manual",
        name: "Start",
        position: { x: 40, y: 40 },
        config: {},
        on_error: "stop",
        retry: null,
      },
    ],
    edges: [],
    settings: EMPTY_GRAPH.settings,
  };
}

function published(graph: Graph) {
  return {
    version: {
      channel_id: "chn_1",
      number: 3,
      published_at: now,
      published_by_user_id: "usr_1",
      published_by_name: "Ada",
      graph,
    },
  };
}

function renderRecord(mode: "show" | "edit") {
  return import("@/features/channels/ChannelRecord").then(({ ChannelRecord }) =>
    render(
      createElement(
        MantineProvider,
        { env: "test" },
        createElement(ChannelRecord, { mode, channelId: "chn_1" }),
      ),
    ),
  );
}

describe("channel rejection drawer", () => {
  beforeEach(() => {
    stubDomApis();
    vi.mocked(getChannel).mockResolvedValue({ channel: channel() });
    vi.mocked(getDraft).mockResolvedValue({
      draft_revision: 1,
      draft_updated_at: now,
      graph: inboundGraph(),
    });
    vi.mocked(listNodeTypes).mockResolvedValue({ items: [spec] });
    vi.mocked(listRuns).mockResolvedValue({ items: [], total: 0, limit: 1, offset: 0 });
    vi.mocked(listChannels).mockResolvedValue({ items: [], total: 0, limit: 200, offset: 0 });
    vi.mocked(getRun).mockResolvedValue({
      run: {
        job_id: "job_1",
        status: "succeeded",
        outcome: "succeeded",
        target: "published",
        version: 1,
        draft_revision: null,
        trigger_kind: "user",
        trigger_ref: null,
        trigger_node_id: "nd_in",
        trigger_actor_name: null,
        trigger_schedule_name: null,
        ignore_checkpoints: false,
        failed_node_id: null,
        created_at: now,
        started_at: now,
        finished_at: now,
        error_code: null,
        error_message: null,
      },
      graph: EMPTY_GRAPH,
      node_summaries: [],
    });
    vi.mocked(listInboundRejections).mockResolvedValue({
      items: [],
      total: 0,
      limit: 50,
      offset: 0,
      hit_count: 4,
    });
    vi.mocked(validateDraft).mockResolvedValue({
      valid: true,
      problems: [],
      ports: [],
      context: { channel: {}, run: {}, platform: {} },
    });
    vi.mocked(saveDraft).mockImplementation(async (_id, body) => ({
      draft_revision: body.base_revision + 1,
      draft_updated_at: now,
      graph: body.graph,
    }));
  });

  afterEach(() => {
    cleanup();
  });

  it("opens refused requests for an inbound channel and shows the dedup hit count", async () => {
    await renderRecord("show");
    fireEvent.click(await screen.findByRole("button", { name: "Rejections" }));

    expect(await screen.findByText("This list is refused requests only.")).toBeTruthy();
    expect(screen.getByText("Deduplication hits: 4")).toBeTruthy();
    expect(screen.getByText("No refused requests")).toBeTruthy();
    expect(screen.queryByRole("row", { name: /4/ })).toBeNull();
    expect(listInboundRejections).toHaveBeenCalledWith("chn_1", { limit: 50, offset: 0 });
  });

  it("lists each refusal with when it arrived and why, and does not show a secret", async () => {
    vi.mocked(listInboundRejections).mockResolvedValue({
      items: [
        rejection("irj_new", "2026-11-02T01:02:03Z", "inactive"),
        rejection("irj_old", "2025-01-15T08:09:10Z", "busy"),
        rejection("irj_raw", "2024-03-04T00:00:00Z", "not_a_known_reason"),
      ],
      total: 3,
      limit: 50,
      offset: 0,
      hit_count: 12,
    });

    await renderRecord("show");
    fireEvent.click(await screen.findByRole("button", { name: "Rejections" }));
    const dialog = await screen.findByRole("dialog", { name: "Rejections" });

    expect(within(dialog).getByText("This list is refused requests only.")).toBeTruthy();
    expect(within(dialog).getByText("Deduplication hits: 12")).toBeTruthy();
    const rows = within(dialog).getAllByRole("row").slice(1);
    expect(rows).toHaveLength(3);
    expect(rows[0]?.textContent).toContain("2026");
    expect(rows[0]?.textContent).toContain("Channel inactive");
    expect(rows[1]?.textContent).toContain("2025");
    expect(rows[1]?.textContent).toContain("In-flight cap reached");
    expect(rows[2]?.textContent).toContain("2024");
    expect(rows[2]?.textContent).toContain("not_a_known_reason");
    const text = dialog.textContent ?? "";
    expect(text).not.toContain("secret-header-value");
    expect(text).not.toContain("secret-query-value");
    expect(text).not.toContain("secret-body-value");
    expect(text).not.toContain("PATCH");
    expect(text).not.toContain("x-token");
  });

  it("opens the rejection list from edit", async () => {
    vi.mocked(listInboundRejections).mockResolvedValue({
      items: [rejection("irj_1", "2026-11-02T01:02:03Z", "unauthenticated")],
      total: 1,
      limit: 50,
      offset: 0,
      hit_count: 0,
    });

    await renderRecord("edit");
    fireEvent.click(await screen.findByRole("button", { name: "Rejections" }));
    const dialog = await screen.findByRole("dialog", { name: "Rejections" });
    expect(within(dialog).getByText("Unauthenticated")).toBeTruthy();
    expect(within(dialog).getByText("Deduplication hits: 0")).toBeTruthy();
    expect(dialog.textContent).not.toContain("secret-header-value");
  });

  it("opens rejections when the published graph is inbound and the draft is not", async () => {
    vi.mocked(getChannel).mockResolvedValue({
      channel: { ...channel(), latest_version: { number: 3, published_at: now } },
    });
    vi.mocked(getDraft).mockResolvedValue({
      draft_revision: 1,
      draft_updated_at: now,
      graph: manualGraph(),
    });
    vi.mocked(listNodeTypes).mockResolvedValue({
      items: [{ ...spec, type: "trigger.manual", label: "Manual" }, spec],
    });
    vi.mocked(getVersion).mockResolvedValue(published(inboundGraph()));

    await renderRecord("show");
    expect(await screen.findByRole("button", { name: "Rejections" })).toBeTruthy();
    cleanup();

    await renderRecord("edit");
    expect(await screen.findByRole("button", { name: "Rejections" })).toBeTruthy();
  });

  it("hides rejections when the published graph is also manual", async () => {
    vi.mocked(getChannel).mockResolvedValue({
      channel: { ...channel(), latest_version: { number: 3, published_at: now } },
    });
    vi.mocked(getDraft).mockResolvedValue({
      draft_revision: 1,
      draft_updated_at: now,
      graph: manualGraph(),
    });
    vi.mocked(listNodeTypes).mockResolvedValue({
      items: [{ ...spec, type: "trigger.manual", label: "Manual" }],
    });
    let settleVersion: (value: ReturnType<typeof published>) => void = () => {};
    vi.mocked(getVersion).mockImplementation(
      () =>
        new Promise((resolve) => {
          settleVersion = resolve;
        }),
    );

    await renderRecord("show");
    expect(await screen.findByRole("button", { name: "channels.tabs.runs" })).toBeTruthy();
    expect(screen.queryByRole("button", { name: "Rejections" })).toBeNull();
    await act(async () => {
      settleVersion(published(manualGraph()));
    });
    expect(screen.queryByRole("button", { name: "Rejections" })).toBeNull();
    cleanup();

    await renderRecord("edit");
    expect(await screen.findByRole("button", { name: "channels.tabs.runs" })).toBeTruthy();
    expect(screen.queryByRole("button", { name: "Rejections" })).toBeNull();
    await act(async () => {
      settleVersion(published(manualGraph()));
    });
    expect(screen.queryByRole("button", { name: "Rejections" })).toBeNull();
  });

  it("hides the rejection list when the channel has no inbound trigger", async () => {
    vi.mocked(getDraft).mockResolvedValue({
      draft_revision: 1,
      draft_updated_at: now,
      graph: manualGraph(),
    });
    vi.mocked(listNodeTypes).mockResolvedValue({
      items: [{ ...spec, type: "trigger.manual", label: "Manual" }],
    });

    await renderRecord("show");
    expect(await screen.findByRole("button", { name: "channels.tabs.runs" })).toBeTruthy();
    expect(screen.queryByRole("button", { name: "Rejections" })).toBeNull();
    cleanup();

    await renderRecord("edit");
    expect(await screen.findByRole("button", { name: "channels.tabs.runs" })).toBeTruthy();
    expect(screen.queryByRole("button", { name: "Rejections" })).toBeNull();
  });

  it("keeps rejection copy in English and Chinese", () => {
    const keys = [
      "channels.tabs.rejections",
      "channels.rejections.refusedOnly",
      "channels.rejections.empty",
      "channels.rejections.received",
      "channels.rejections.reason",
      "channels.rejections.hitCount",
      "channels.rejections.reason.inactive",
      "channels.rejections.reason.method_not_allowed",
      "channels.rejections.reason.body_too_large",
      "channels.rejections.reason.unauthenticated",
      "channels.rejections.reason.input_invalid",
      "channels.rejections.reason.duplicate_in_flight",
      "channels.rejections.reason.busy",
    ];
    const zhCopy: Record<string, string> = {
      "channels.tabs.rejections": "\u62d2\u7edd",
      "channels.rejections.refusedOnly":
        "\u6b64\u5217\u8868\u53ea\u6709\u88ab\u62d2\u7edd\u7684\u8bf7\u6c42\u3002",
      "channels.rejections.empty": "\u8fd8\u6ca1\u6709\u88ab\u62d2\u7edd\u7684\u8bf7\u6c42",
      "channels.rejections.received": "\u5230\u8fbe",
      "channels.rejections.reason": "\u539f\u56e0",
      "channels.rejections.hitCount": "\u53bb\u91cd\u547d\u4e2d\uff1a{{count}}",
      "channels.rejections.reason.inactive": "\u901a\u9053\u672a\u542f\u7528",
      "channels.rejections.reason.method_not_allowed": "\u65b9\u6cd5\u4e0d\u5141\u8bb8",
      "channels.rejections.reason.body_too_large": "\u8bf7\u6c42\u4f53\u8fc7\u5927",
      "channels.rejections.reason.unauthenticated": "\u672a\u901a\u8fc7\u8ba4\u8bc1",
      "channels.rejections.reason.input_invalid": "\u8f93\u5165\u65e0\u6548",
      "channels.rejections.reason.duplicate_in_flight":
        "\u91cd\u590d\u8bf7\u6c42\u4ecd\u5728\u5904\u7406",
      "channels.rejections.reason.busy": "\u5728\u9014\u5df2\u8fbe\u4e0a\u9650",
    };
    for (const key of keys) {
      expect(en[key as keyof typeof en], key).toBeTruthy();
      expect(zh[key as keyof typeof zh], key).toBe(zhCopy[key]);
      expect(zh[key as keyof typeof zh]).not.toBe(en[key as keyof typeof en]);
    }
    expect(en["channels.rejections.refusedOnly"]).toBe("This list is refused requests only.");
    expect(en["channels.rejections.hitCount"]).toBe("Deduplication hits: {{count}}");
    expect(en["channels.runs.trigger.inbound"]).toBe("Inbound");
    expect(zh["channels.runs.trigger.inbound"]).toBe("\u5165\u7ad9");
  });
});
