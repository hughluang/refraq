/** @vitest-environment jsdom */

import { MantineProvider } from "@mantine/core";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { createElement, type ReactNode } from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import {
  activateChannel,
  createChannel,
  getChannel,
  getDraft,
  getRun,
  listChannels,
  listNodeTypes,
  listRuns,
  patchChannel,
  replaceChannelTags,
  saveDraft,
  validateDraft,
} from "@/features/channels/api";
import { listTags } from "@/features/tags/api";
import { EMPTY_GRAPH, type Channel, type ChannelRunDetail, type NodeTypeSpec } from "@/features/channels/types";

const flags = vi.hoisted(() => ({ canWrite: true }));

vi.mock("@refinedev/core", () => ({
  useTranslate: () => (key: string, values?: Record<string, unknown>) => {
    if (!values) return key;
    return key.replace(/\{\{(\w+)\}\}/g, (_, name: string) => String(values[name] ?? ""));
  },
  useNotification: () => ({ open: vi.fn() }),
  useCan: () => ({ data: { can: flags.canWrite } }),
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

function channel(overrides: Partial<Channel> = {}): Channel {
  return {
    id: "chn_1",
    name: "Intake",
    description: null,
    active: false,
    draft_revision: 4,
    draft_updated_at: now,
    latest_version: null,
    failure_streak: 0,
    persistently_failing: false,
    tags: [],
    tag_revision: 1,
    created_at: now,
    updated_at: now,
    ...overrides,
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
      draft_revision: 4,
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

function button(name: string) {
  return screen.getByRole("button", { name: (value) => value === name }) as HTMLButtonElement;
}

async function renderRecord(mode: "show" | "edit" | "create" = "show") {
  const { ChannelRecord } = await import("@/features/channels/ChannelRecord");
  const node =
    mode === "create"
      ? createElement(ChannelRecord, { mode: "create" })
      : createElement(ChannelRecord, { mode, channelId: "chn_1" });
  render(createElement(MantineProvider, { env: "test" }, node));
}

describe("ChannelRecord tags", { timeout: 15_000 }, () => {
  beforeEach(() => {
    stubDomApis();
    flags.canWrite = true;
    vi.clearAllMocks();
    vi.mocked(getChannel).mockResolvedValue({ channel: channel() });
    vi.mocked(getDraft).mockResolvedValue({
      draft_revision: 4,
      draft_updated_at: now,
      graph: EMPTY_GRAPH,
    });
    vi.mocked(listNodeTypes).mockResolvedValue({ items: [spec] });
    vi.mocked(listRuns).mockResolvedValue({ items: [], total: 0, limit: 1, offset: 0 });
    vi.mocked(listChannels).mockResolvedValue({ items: [], total: 0, limit: 200, offset: 0 });
    vi.mocked(validateDraft).mockResolvedValue({
      valid: true,
      problems: [],
      ports: [],
      context: { channel: {}, run: {}, platform: {} },
    });
    vi.mocked(listTags).mockResolvedValue({ items: [], total: 0, limit: 8, offset: 0 });
    vi.mocked(replaceChannelTags).mockResolvedValue({
      tags: [{ id: "tag_ledger", name: "Ledger" }],
      tag_revision: 2,
    });
  });

  afterEach(() => {
    cleanup();
  });

  it("saves show-page tags through PUT and leaves the draft save alone", async () => {
    await renderRecord("show");
    expect(await screen.findByRole("heading", { name: "Intake" })).toBeTruthy();

    const field = screen.getByRole("textbox", { name: "channels.tags.field" });
    fireEvent.change(field, { target: { value: "Ledger" } });
    fireEvent.keyDown(field, { key: "Enter" });
    expect(button("channels.actions.publish").disabled).toBe(false);

    fireEvent.click(button("channels.tags.save"));
    await waitFor(() => {
      expect(replaceChannelTags).toHaveBeenCalledWith("chn_1", {
        base_revision: 1,
        tag_ids: [],
        names: ["Ledger"],
      });
    });
    expect(button("channels.tags.remove")).toBeTruthy();
    expect(patchChannel).not.toHaveBeenCalled();
    expect(saveDraft).not.toHaveBeenCalled();
    expect(button("channels.actions.publish").disabled).toBe(false);
  });

  it("saves a suggested tag by its name as that tag id", async () => {
    vi.mocked(listTags).mockResolvedValue({
      items: [
        {
          id: "tag_ledger",
          name: "Ledger",
          description: null,
          created_at: now,
          updated_at: now,
        },
      ],
      total: 1,
      limit: 8,
      offset: 0,
    });
    await renderRecord("show");
    expect(await screen.findByRole("heading", { name: "Intake" })).toBeTruthy();

    fireEvent.change(screen.getByRole("textbox", { name: "channels.tags.field" }), {
      target: { value: "Led" },
    });
    fireEvent.click(await screen.findByRole("option", { name: (value) => value === "Ledger" }));
    fireEvent.click(button("channels.tags.save"));

    await waitFor(() => {
      expect(replaceChannelTags).toHaveBeenCalledWith("chn_1", {
        base_revision: 1,
        tag_ids: ["tag_ledger"],
        names: [],
      });
    });
    expect(patchChannel).not.toHaveBeenCalled();
    expect(saveDraft).not.toHaveBeenCalled();
  });

  it("keeps tag editing available while a draft run locks the graph", async () => {
    vi.mocked(listRuns).mockResolvedValue({
      items: [runningDetail().run],
      total: 1,
      limit: 1,
      offset: 0,
    });
    vi.mocked(getRun).mockResolvedValue(runningDetail());
    await renderRecord("edit");
    expect(await screen.findByRole("button", { name: "channels.run.stop" })).toBeTruthy();

    expect((button("channels.canvas.add") as HTMLButtonElement).disabled).toBe(true);
    expect((button("channels.edit.submit") as HTMLButtonElement).disabled).toBe(true);
    expect((button("channels.actions.publish") as HTMLButtonElement).disabled).toBe(true);
    expect((button("channels.run.open") as HTMLButtonElement).disabled).toBe(true);
    expect(screen.queryByRole("button", { name: "channels.name.edit" })).toBeNull();
    expect(screen.queryByRole("switch", { name: "channels.fields.active" })).toBeNull();

    fireEvent.click(button("channels.details.title"));
    expect(screen.queryByRole("textbox", { name: "channels.fields.description" })).toBeNull();
    expect(screen.queryByRole("button", { name: "channels.description.apply" })).toBeNull();

    const field = screen.getByRole("textbox", { name: "channels.tags.field" });
    fireEvent.change(field, { target: { value: "Ledger" } });
    fireEvent.keyDown(field, { key: "Enter" });
    expect((button("channels.tags.save") as HTMLButtonElement).disabled).toBe(false);
    fireEvent.click(button("channels.tags.save"));
    await waitFor(() => {
      expect(replaceChannelTags).toHaveBeenCalledWith("chn_1", {
        base_revision: 1,
        tag_ids: [],
        names: ["Ledger"],
      });
    });
    expect(saveDraft).not.toHaveBeenCalled();
    expect(patchChannel).not.toHaveBeenCalled();
    expect((button("channels.edit.submit") as HTMLButtonElement).disabled).toBe(true);
    expect((button("channels.actions.publish") as HTMLButtonElement).disabled).toBe(true);
  });

  it("sends committed tag names with the create body", async () => {
    vi.mocked(createChannel).mockImplementation(() => new Promise(() => {}));
    await renderRecord("create");
    fireEvent.change(await screen.findByRole("textbox", { name: "channels.fields.name" }), {
      target: { value: "Intake" },
    });
    fireEvent.change(screen.getByRole("textbox", { name: "channels.fields.description" }), {
      target: { value: "From the plant" },
    });
    const field = screen.getByRole("textbox", { name: "channels.tags.field" });
    fireEvent.change(field, { target: { value: "Ledger" } });
    fireEvent.keyDown(field, { key: "Enter" });
    expect(screen.queryByRole("button", { name: "channels.tags.save" })).toBeNull();
    fireEvent.click(button("channels.create.submit"));
    await waitFor(() => {
      expect(createChannel).toHaveBeenCalledWith({
        name: "Intake",
        description: "From the plant",
        tags: { tag_ids: [], names: ["Ledger"] },
      });
    });
    expect(replaceChannelTags).not.toHaveBeenCalled();
  });

  it("sends the tag field text with the create body without Enter", async () => {
    vi.mocked(createChannel).mockImplementation(() => new Promise(() => {}));
    await renderRecord("create");
    fireEvent.change(await screen.findByRole("textbox", { name: "channels.fields.name" }), {
      target: { value: "Intake" },
    });
    const tagField = screen.getByRole("textbox", { name: "channels.tags.field" });
    expect(screen.getByText("channels.tags.empty")).toBeTruthy();
    fireEvent.change(tagField, { target: { value: "Ledger" } });
    expect(screen.queryByText("channels.tags.empty")).toBeNull();
    expect(screen.queryByRole("button", { name: "channels.tags.remove" })).toBeNull();
    fireEvent.change(tagField, { target: { value: "   " } });
    expect(screen.getByText("channels.tags.empty")).toBeTruthy();
    fireEvent.change(tagField, { target: { value: "" } });
    expect(screen.getByText("channels.tags.empty")).toBeTruthy();
    fireEvent.change(tagField, { target: { value: "Ledger" } });
    expect(screen.queryByText("channels.tags.empty")).toBeNull();
    expect(screen.getByText("channels.tags.createDescription")).toBeTruthy();
    expect(screen.queryByRole("button", { name: "channels.tags.save" })).toBeNull();
    fireEvent.click(button("channels.create.submit"));
    await waitFor(() => {
      expect(createChannel).toHaveBeenCalledWith({
        name: "Intake",
        description: null,
        tags: { tag_ids: [], names: ["Ledger"] },
      });
    });
    expect(replaceChannelTags).not.toHaveBeenCalled();
  });

  it("sends the tag field text when save tags is clicked without Enter", async () => {
    await renderRecord("show");
    expect(await screen.findByRole("heading", { name: "Intake" })).toBeTruthy();

    expect(await screen.findByText("channels.tags.empty")).toBeTruthy();
    fireEvent.change(screen.getByRole("textbox", { name: "channels.tags.field" }), {
      target: { value: "Ledger" },
    });
    expect(screen.queryByText("channels.tags.empty")).toBeNull();
    expect(screen.queryByRole("button", { name: "channels.tags.remove" })).toBeNull();
    fireEvent.click(button("channels.tags.save"));
    await waitFor(() => {
      expect(replaceChannelTags).toHaveBeenCalledWith("chn_1", {
        base_revision: 1,
        tag_ids: [],
        names: ["Ledger"],
      });
    });
  });

  it("keeps an unsaved tag name when a definition save returns the same assignment", async () => {
    vi.mocked(activateChannel).mockResolvedValue({
      channel: channel({
        active: true,
        updated_at: "2026-01-02T00:00:00Z",
        tags: [],
      }),
    });
    await renderRecord("edit");
    const field = await screen.findByRole("textbox", { name: "channels.tags.field" });
    fireEvent.change(field, { target: { value: "Ledger" } });
    fireEvent.keyDown(field, { key: "Enter" });
    expect(button("channels.tags.remove")).toBeTruthy();

    fireEvent.click(screen.getByRole("switch", { name: "channels.fields.active" }));
    fireEvent.click(button("channels.edit.submit"));
    await waitFor(() => {
      expect(activateChannel).toHaveBeenCalledWith("chn_1");
    });
    expect(button("channels.tags.remove")).toBeTruthy();
    expect(replaceChannelTags).not.toHaveBeenCalled();
  });

  it("shows tags without an editor when the operator cannot write channels", async () => {
    flags.canWrite = false;
    vi.mocked(getChannel).mockResolvedValue({
      channel: channel({ tags: [{ id: "tag_ledger", name: "Ledger" }] }),
    });
    await renderRecord("show");
    expect(await screen.findByText("Ledger")).toBeTruthy();
    expect(screen.queryByRole("textbox", { name: "channels.tags.field" })).toBeNull();
    expect(screen.queryByRole("button", { name: "channels.tags.save" })).toBeNull();
  });

  it("shows create-page tags without an editor when the operator cannot write channels", async () => {
    flags.canWrite = false;
    await renderRecord("create");
    expect(await screen.findByText("channels.tags.empty")).toBeTruthy();
    expect(screen.queryByRole("textbox", { name: "channels.tags.field" })).toBeNull();
    expect(screen.queryByRole("button", { name: "channels.tags.save" })).toBeNull();
  });
});
