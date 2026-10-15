/** @vitest-environment jsdom */

import { MantineProvider } from "@mantine/core";
import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { createElement, type ReactNode } from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import {
  getChannel,
  getDraft,
  getRun,
  listNodeTypes,
  listRuns,
  saveDraft,
  startRun,
  validateDraft,
} from "@/features/channels/api";
import { EMPTY_GRAPH, type Channel, type ChannelRunDetail, type NodeTypeSpec } from "@/features/channels/types";
import { Instant } from "@/lib/instant";

vi.mock("@refinedev/core", () => ({
  useTranslate: () => (key: string, options?: { defaultValue?: string }) =>
    options?.defaultValue ?? key,
  useNotification: () => ({ open: vi.fn() }),
  useCan: () => ({ data: { can: true } }),
  usePermissions: () => ({ data: [] as string[] }),
  useBreadcrumb: () => ({ breadcrumbs: [] }),
}));

vi.mock("next/link", () => ({
  default: ({ href, children, ...props }: { href: string; children: ReactNode }) =>
    createElement("a", { href, ...props }, children),
}));

vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: vi.fn(), replace: vi.fn() }),
}));

vi.mock("@/features/channels/api", () => ({
  activateChannel: vi.fn(),
  createChannel: vi.fn(),
  deactivateChannel: vi.fn(),
  deleteChannel: vi.fn(),
  getChannel: vi.fn(),
  getDraft: vi.fn(),
  getRun: vi.fn(),
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

const now = Instant.parse("2026-01-01T00:00:00Z");

const spec: NodeTypeSpec = {
  type: "manual",
  family: "trigger",
  label: "Manual",
  summary: "Start here",
  description: "",
  entry: true,
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
    node_executions: [],
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

  it("keeps undo history when a draft save does not reload the canvas", async () => {
    await renderRecord("edit");
    const add = await screen.findByRole("button", { name: "channels.canvas.add" });
    fireEvent.click(add);
    fireEvent.click(screen.getByRole("button", { name: /Manual/ }));
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
});
