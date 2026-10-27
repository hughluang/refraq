/** @vitest-environment jsdom */

import { MantineProvider } from "@mantine/core";
import { act, cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { createElement, type ReactNode } from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import {
  getChannel,
  getDraft,
  getRun,
  listNodeTypes,
  listRuns,
  previewPublish,
  publishChannel,
  saveDraft,
  startRun,
  validateDraft,
} from "@/features/channels/api";
import en from "@/locales/en-US/common.json";
import zh from "@/locales/zh-CN/common.json";
import {
  EMPTY_GRAPH,
  type Channel,
  type ChannelRunDetail,
  type Confirmation,
  type NodeTypeSpec,
} from "@/features/channels/types";

vi.mock("@refinedev/core", () => ({
  useTranslate: () => (key: string, options?: { defaultValue?: string }) =>
    options?.defaultValue ?? key,
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

function triggerGraph() {
  return {
    nodes: [
      {
        id: "nd_1",
        ref: "run_manually",
        type: "trigger.manual",
        name: "Start",
        position: { x: 40, y: 40 },
        config: {},
        on_error: "stop" as const,
        retry: null,
      },
    ],
    edges: [],
    settings: EMPTY_GRAPH.settings,
  };
}

const publishPreview: Confirmation = {
  draft_revision: 1,
  mirrors_to_open: [],
  runs_to_cancel: [],
  missing_run_timeout: false,
};

function clickTwice(node: HTMLElement) {
  act(() => {
    node.click();
    node.click();
  });
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

describe("ChannelRecord draft access", () => {
  beforeEach(() => {
    stubDomApis();
    vi.mocked(getChannel).mockResolvedValue({ channel: channel() });
    vi.mocked(getDraft).mockResolvedValue({
      draft_revision: 1,
      draft_updated_at: now,
      graph: EMPTY_GRAPH,
    });
    vi.mocked(listNodeTypes).mockResolvedValue({ items: [spec] });
    vi.mocked(listRuns).mockResolvedValue({ items: [], total: 0, limit: 1, offset: 0 });
    vi.mocked(getRun).mockResolvedValue(runningDetail());
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
    vi.clearAllMocks();
  });

  it("does not offer a run from the show page", async () => {
    await renderRecord("show");
    expect(await screen.findByRole("heading", { name: "Intake" })).toBeTruthy();
    expect(screen.queryByRole("button", { name: "channels.run.open" })).toBeNull();
  });

  it("refuses to save while the latest draft run is still going", async () => {
    vi.mocked(listRuns).mockResolvedValue({
      items: [{ ...runningDetail().run }],
      total: 1,
      limit: 1,
      offset: 0,
    });
    await renderRecord("edit");
    expect(await screen.findByRole("button", { name: "channels.run.stop" })).toBeTruthy();
    expect(document.querySelector(".channel-canvas-stage--browse")).toBeNull();
    expect((screen.getByRole("button", { name: "channels.canvas.add" }) as HTMLButtonElement).disabled).toBe(
      true,
    );
    expect((screen.getByRole("button", { name: "channels.edit.submit" }) as HTMLButtonElement).disabled).toBe(
      true,
    );
    expect((screen.getByRole("button", { name: "channels.run.open" }) as HTMLButtonElement).disabled).toBe(
      true,
    );

    const form = document.getElementById("channel-record-form");
    if (!(form instanceof HTMLFormElement)) throw new Error("missing form");
    fireEvent.submit(form);
    await waitFor(() => {
      expect(saveDraft).not.toHaveBeenCalled();
    });
  });

  it("saves a draft note beside the nodes", async () => {
    await renderRecord("edit");
    fireEvent.click(await screen.findByRole("button", { name: "channels.canvas.note" }));
    const field = await screen.findByRole("textbox", { name: "channels.canvas.noteLabel" });
    fireEvent.change(field, { target: { value: "remember\nthis" } });
    fireEvent.blur(field);
    fireEvent.click(screen.getByRole("button", { name: "channels.edit.submit" }));
    await waitFor(() => expect(saveDraft).toHaveBeenCalledTimes(1));
    const body = vi.mocked(saveDraft).mock.calls[0]?.[1];
    expect(body?.graph.notes).toEqual([
      expect.objectContaining({
        text: "remember\nthis",
        size: { width: 240, height: 120 },
      }),
    ]);
    expect(body?.graph.nodes.map((node) => node.id)).not.toContain(body?.graph.notes?.[0]?.id);
    expect(body?.graph).not.toHaveProperty("nodes", expect.arrayContaining([expect.objectContaining({ text: "remember\nthis" })]));
  });

  it("keeps undo history when a draft save does not reload the canvas", async () => {
    await renderRecord("edit");
    const panel = await screen.findByRole("toolbar", { name: "channels.canvas.toolbar" });
    const add = within(panel).getByRole("button", { name: "channels.canvas.add" });
    fireEvent.click(add);
    fireEvent.click(screen.getByRole("option", { name: /Manual/ }));
    const undo = screen.getByRole("button", { name: "channels.canvas.undo" });
    expect((undo as HTMLButtonElement).disabled).toBe(false);

    fireEvent.click(screen.getByRole("button", { name: "channels.edit.submit" }));
    await waitFor(() => {
      expect(saveDraft).toHaveBeenCalledTimes(1);
    });
    expect((screen.getByRole("button", { name: "channels.canvas.undo" }) as HTMLButtonElement).disabled).toBe(
      false,
    );
    expect(document.querySelector(".channel-flow-node")?.textContent).toContain("Manual");
  });

  it("opens the same run confirmation from the header and a node", async () => {
    const graph = {
      nodes: [
        {
          id: "nd_1",
          ref: "run_manually",
          type: "trigger.manual",
          name: "Start",
          position: { x: 40, y: 40 },
          config: {},
          on_error: "stop" as const,
          retry: null,
        },
      ],
      edges: [],
      settings: EMPTY_GRAPH.settings,
    };
    vi.mocked(getDraft).mockResolvedValue({
      draft_revision: 1,
      draft_updated_at: now,
      graph,
    });
    vi.mocked(listNodeTypes).mockResolvedValue({
      items: [{ ...spec, type: "trigger.manual" }],
    });
    vi.mocked(startRun).mockResolvedValue({ run: runningDetail().run });

    await renderRecord("edit");
    const header = await screen.findByRole("button", { name: "channels.run.open" });
    fireEvent.click(header);
    const headerDialog = await screen.findByRole("dialog");
    expect(headerDialog.textContent).toContain("channels.run.writes");
    expect(startRun).not.toHaveBeenCalled();
    fireEvent.click(within(headerDialog).getByRole("button", { name: "common.cancel" }));
    await waitFor(() => {
      expect(screen.queryByRole("dialog")).toBeNull();
    });

    const node = document.querySelector(".react-flow__node");
    if (!(node instanceof HTMLElement)) throw new Error("missing node");
    fireEvent.click(node);
    const nodeRun = document.querySelector(".channel-flow-node__run");
    if (!(nodeRun instanceof HTMLButtonElement)) throw new Error("missing node run button");
    fireEvent.click(nodeRun);
    const nodeDialog = await screen.findByRole("dialog");
    expect(nodeDialog.textContent).toContain("channels.run.writesUpTo");
    expect(within(nodeDialog).getByRole("button", { name: "channels.run.confirm" })).toBeTruthy();
    expect(startRun).not.toHaveBeenCalled();

    fireEvent.click(within(nodeDialog).getByRole("button", { name: "channels.run.confirm" }));
    await waitFor(() => {
      expect(startRun).toHaveBeenCalledWith("chn_1", {
        target: "draft",
        ignore_checkpoints: false,
        stop_at_node_id: "nd_1",
      });
    });
  });

  it("runs the whole graph from the header", async () => {
    const graph = {
      nodes: [
        {
          id: "nd_1",
          ref: "run_manually",
          type: "trigger.manual",
          name: "Start",
          position: { x: 40, y: 40 },
          config: {},
          on_error: "stop" as const,
          retry: null,
        },
      ],
      edges: [],
      settings: EMPTY_GRAPH.settings,
    };
    vi.mocked(getDraft).mockResolvedValue({ draft_revision: 1, draft_updated_at: now, graph });
    vi.mocked(listNodeTypes).mockResolvedValue({ items: [{ ...spec, type: "trigger.manual" }] });
    vi.mocked(startRun).mockResolvedValue({ run: runningDetail().run });

    await renderRecord("edit");
    fireEvent.click(await screen.findByRole("button", { name: "channels.run.open" }));
    const dialog = await screen.findByRole("dialog");
    expect(dialog.textContent).not.toContain("channels.run.writesUpTo");
    fireEvent.click(within(dialog).getByRole("button", { name: "channels.run.confirm" }));
    await waitFor(() => {
      expect(startRun).toHaveBeenCalledWith("chn_1", {
        target: "draft",
        ignore_checkpoints: false,
        stop_at_node_id: null,
      });
    });
  });

  it("enqueues one run when confirm is clicked twice in one turn", async () => {
    vi.mocked(getDraft).mockResolvedValue({
      draft_revision: 1,
      draft_updated_at: now,
      graph: triggerGraph(),
    });
    vi.mocked(listNodeTypes).mockResolvedValue({
      items: [{ ...spec, type: "trigger.manual", label: "Manual" }],
    });
    let resolveRun: (value: { run: ChannelRunDetail["run"] }) => void = () => {};
    vi.mocked(startRun).mockImplementation(
      () =>
        new Promise((resolve) => {
          resolveRun = resolve;
        }),
    );

    await renderRecord("edit");
    fireEvent.click(await screen.findByRole("button", { name: "channels.run.open" }));
    const confirm = within(await screen.findByRole("dialog")).getByRole("button", {
      name: "channels.run.confirm",
    });
    clickTwice(confirm);
    await waitFor(() => {
      expect(startRun).toHaveBeenCalledTimes(1);
    });
    await act(async () => {
      resolveRun(runningDetail().run);
    });
  });

  it("previews publish once when the button is clicked twice in one turn", async () => {
    vi.mocked(previewPublish).mockResolvedValue(publishPreview);
    await renderRecord("edit");
    const publish = await screen.findByRole("button", { name: "channels.actions.publish" });
    clickTwice(publish);
    await waitFor(() => {
      expect(previewPublish).toHaveBeenCalledTimes(1);
    });
  });

  it("publishes once when confirm is clicked twice in one turn", async () => {
    vi.mocked(previewPublish).mockResolvedValue(publishPreview);
    let resolvePublish: (value: unknown) => void = () => {};
    vi.mocked(publishChannel).mockImplementation(
      () =>
        new Promise((resolve) => {
          resolvePublish = resolve;
        }),
    );

    await renderRecord("edit");
    fireEvent.click(await screen.findByRole("button", { name: "channels.actions.publish" }));
    const confirm = within(await screen.findByRole("dialog")).getByRole("button", {
      name: "channels.publish.confirm",
    });
    clickTwice(confirm);
    expect(publishChannel).toHaveBeenCalledTimes(1);
    await act(async () => {
      resolvePublish({});
    });
  });

  it("lets the first of save and run accept the page latch", async () => {
    vi.mocked(getDraft).mockResolvedValue({
      draft_revision: 1,
      draft_updated_at: now,
      graph: triggerGraph(),
    });
    vi.mocked(listNodeTypes).mockResolvedValue({
      items: [
        { ...spec, type: "trigger.manual", label: "Manual" },
        { ...spec, type: "transform.filter", label: "Filter", trigger: false },
      ],
    });
    vi.mocked(startRun).mockResolvedValue({ run: runningDetail().run });
    vi.mocked(previewPublish).mockResolvedValue(publishPreview);

    await renderRecord("edit");
    fireEvent.click(await screen.findByRole("button", { name: "channels.canvas.add" }));
    fireEvent.click(screen.getByRole("option", { name: /Filter/ }));
    fireEvent.click(screen.getByRole("button", { name: "channels.run.open" }));
    const dialog = await screen.findByRole("dialog");
    const confirm = within(dialog).getByRole("button", { name: "channels.run.confirm" });
    const save = screen.getByRole("button", { name: "channels.edit.submit" });
    const publish = screen.getByRole("button", { name: "channels.actions.publish" });

    act(() => {
      confirm.click();
      save.click();
      publish.click();
    });
    await waitFor(() => {
      expect(startRun).toHaveBeenCalledTimes(1);
    });
    expect(saveDraft).toHaveBeenCalledTimes(1);
    expect(previewPublish).not.toHaveBeenCalled();

    cleanup();
    vi.mocked(startRun).mockClear();
    vi.mocked(saveDraft).mockClear();
    vi.mocked(previewPublish).mockClear();
    await renderRecord("edit");
    fireEvent.click(await screen.findByRole("button", { name: "channels.canvas.add" }));
    fireEvent.click(screen.getByRole("option", { name: /Filter/ }));
    fireEvent.click(screen.getByRole("button", { name: "channels.run.open" }));
    const secondDialog = await screen.findByRole("dialog");
    const secondConfirm = within(secondDialog).getByRole("button", { name: "channels.run.confirm" });
    act(() => {
      screen.getByRole("button", { name: "channels.edit.submit" }).click();
      secondConfirm.click();
      screen.getByRole("button", { name: "channels.actions.publish" }).click();
    });
    await waitFor(() => {
      expect(saveDraft).toHaveBeenCalledTimes(1);
    });
    expect(startRun).not.toHaveBeenCalled();
    expect(previewPublish).not.toHaveBeenCalled();
  });
});

describe("run confirmation copy", () => {
  it("states the execution scope and the save, without a write or dry-run claim", () => {
    expect(zh["channels.run.writes"]).toBe(
      "\u5c06\u8fd0\u884c\u5f53\u524d\u753b\u5e03\u4e2d\u7684\u56fe\u3002\u672a\u4fdd\u5b58\u7684\u6539\u52a8\u4f1a\u5148\u4fdd\u5b58\u3002",
    );
    expect(zh["channels.run.writesUpTo"]).toBe(
      "\u5c06\u8fd0\u884c\u300c{{node}}\u300d\u53ca\u5176\u4e0a\u6e38\u8282\u70b9\uff0c\u4e0b\u6e38\u8282\u70b9\u4e0d\u8fd0\u884c\u3002\u672a\u4fdd\u5b58\u7684\u6539\u52a8\u4f1a\u5148\u4fdd\u5b58\u3002",
    );
    expect(en["channels.run.writes"]).toBe(
      "This runs the graph on the canvas. Unsaved changes are saved first.",
    );
    expect(en["channels.run.writesUpTo"]).toBe(
      "This runs {{node}} and the nodes upstream of it. Downstream nodes do not run. Unsaved changes are saved first.",
    );
  });
});
