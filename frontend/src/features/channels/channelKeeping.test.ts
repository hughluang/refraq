/** @vitest-environment jsdom */

import { MantineProvider } from "@mantine/core";
import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { createElement, type ReactNode } from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import {
  getChannel,
  getDraft,
  getRun,
  getVersion,
  listChannels,
  listNodeTypes,
  listRuns,
  saveDraft,
  validateDraft,
} from "@/features/channels/api";
import { EMPTY_GRAPH, type Channel, type Graph, type NodeTypeSpec } from "@/features/channels/types";

const LABELS: Record<string, string> = {
  "channels.settings.keepSucceededRuns": "Keep succeeded runs",
  "channels.settings.keepFailedRuns": "Keep failed runs",
  "channels.settings.keepTestRuns": "Keep test runs",
  "channels.settings.inboundKeepingBoundary": "Accepted requests then leave no record.",
  "form.value.yes": "Yes",
  "form.value.no": "No",
};

vi.mock("@refinedev/core", () => ({
  matchResourceFromRoute: () => ({ found: false }),
  useTranslate: () => (key: string, options?: { defaultValue?: string }) =>
    LABELS[key] ?? options?.defaultValue ?? key,
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

function channel(latest: Channel["latest_version"]): Channel {
  return {
    id: "chn_1",
    name: "Intake",
    description: null,
    active: false,
    draft_revision: 1,
    draft_updated_at: now,
    latest_version: latest,
    failure_streak: 0,
    persistently_failing: false,
    tags: [],
    tag_revision: 1,
    created_at: now,
    updated_at: now,
  };
}

function inboundNode(path: string) {
  return {
    id: "nd_in",
    ref: "in",
    type: "trigger.inbound",
    name: "In",
    position: { x: 40, y: 40 },
    config: {
      path,
      credential_id: "icr_1",
      response: { mode: "immediate", body: { kind: "static", text: "" } },
    },
    on_error: "stop" as const,
    retry: null,
  };
}

function graph(path: string, settings: Graph["settings"] = EMPTY_GRAPH.settings): Graph {
  return { nodes: [inboundNode(path)], edges: [], settings };
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

describe("channel keeping settings", () => {
  beforeEach(() => {
    stubDomApis();
    vi.mocked(getChannel).mockResolvedValue({ channel: channel(null) });
    vi.mocked(getDraft).mockResolvedValue({
      draft_revision: 1,
      draft_updated_at: now,
      graph: graph("draft-path"),
    });
    vi.mocked(listNodeTypes).mockResolvedValue({ items: [spec] });
    vi.mocked(listRuns).mockResolvedValue({ items: [], total: 0, limit: 1, offset: 0 });
    vi.mocked(listChannels).mockResolvedValue({ items: [], total: 0, limit: 200, offset: 0 });
    vi.mocked(getRun).mockResolvedValue({
      run: {
        job_id: "job_1",
        status: "succeeded",
        outcome: "succeeded",
        target: "draft",
        version: null,
        draft_revision: 1,
        trigger_kind: "user",
        trigger_ref: "in",
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

  it("defaults the three keeping switches on and states the inbound boundary only when succeeded runs are discarded", async () => {
    await renderRecord("edit");
    fireEvent.click(await screen.findByRole("button", { name: "channels.details.title" }));
    const dialog = await screen.findByRole("dialog");
    const succeeded = within(dialog).getByRole("switch", { name: "Keep succeeded runs" });
    const failed = within(dialog).getByRole("switch", { name: "Keep failed runs" });
    const tests = within(dialog).getByRole("switch", { name: "Keep test runs" });
    expect((succeeded as HTMLInputElement).checked).toBe(true);
    expect((failed as HTMLInputElement).checked).toBe(true);
    expect((tests as HTMLInputElement).checked).toBe(true);
    expect(dialog.textContent).not.toContain("Accepted requests then leave no record.");

    fireEvent.click(succeeded);
    expect(dialog.textContent).toContain("Accepted requests then leave no record.");
    fireEvent.click(within(dialog).getByRole("button", { name: "channels.description.apply" }));
    await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());
    expect(saveDraft).not.toHaveBeenCalled();

    fireEvent.click(screen.getByRole("button", { name: "channels.edit.submit" }));
    await waitFor(() => expect(saveDraft).toHaveBeenCalledTimes(1));
    expect(vi.mocked(saveDraft).mock.calls[0]?.[1].graph.settings).toMatchObject({
      keep_succeeded_runs: false,
      keep_failed_runs: true,
      keep_test_runs: true,
    });
  });

  it("hides the boundary sentence when the trigger is not inbound", async () => {
    vi.mocked(getDraft).mockResolvedValue({
      draft_revision: 1,
      draft_updated_at: now,
      graph: {
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
        settings: {
          ...EMPTY_GRAPH.settings,
          keep_succeeded_runs: false,
        },
      },
    });
    vi.mocked(listNodeTypes).mockResolvedValue({
      items: [{ ...spec, type: "trigger.manual", label: "Manual" }],
    });

    await renderRecord("edit");
    fireEvent.click(await screen.findByRole("button", { name: "channels.details.title" }));
    const dialog = await screen.findByRole("dialog");
    expect(
      (within(dialog).getByRole("switch", { name: "Keep succeeded runs" }) as HTMLInputElement)
        .checked,
    ).toBe(false);
    expect(dialog.textContent).not.toContain("Accepted requests then leave no record.");
  });

  it("shows the published hook path, not the draft path, after that version is published", async () => {
    vi.mocked(getChannel).mockResolvedValue({
      channel: channel({ number: 3, published_at: now }),
    });
    vi.mocked(getVersion).mockResolvedValue({
      version: {
        channel_id: "chn_1",
        number: 3,
        published_at: now,
        published_by_user_id: "usr_1",
        published_by_name: "Ada",
        graph: graph("orders"),
      },
    });

    await renderRecord("edit");
    await waitFor(() => expect(getVersion).toHaveBeenCalledWith("chn_1", 3));
    const node = document.querySelector(".react-flow__node");
    if (!(node instanceof HTMLElement)) throw new Error("missing node");
    node.focus();
    fireEvent.keyDown(node, { key: "Enter" });
    expect(await screen.findByText("http://localhost:3000/api/hooks/orders")).toBeTruthy();
    expect(screen.queryByText("http://localhost:3000/api/hooks/draft-path")).toBeNull();
  });
});
