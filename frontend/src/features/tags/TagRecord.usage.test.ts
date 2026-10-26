/** @vitest-environment jsdom */

import { MantineProvider } from "@mantine/core";
import { cleanup, render, screen, waitFor } from "@testing-library/react";
import { createElement, type ReactNode } from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { listChannels } from "@/features/channels/api";
import type { Channel } from "@/features/channels/types";
import { listEntities } from "@/features/entities/api";
import type { BusinessEntity } from "@/features/entities/types";
import { getTag } from "@/features/tags/api";
import type { Tag } from "@/features/tags/types";
import en from "@/locales/en-US/common.json";
import zh from "@/locales/zh-CN/common.json";

const TAG_ID = "tag_0123456789ab";

const access = vi.hoisted(() => ({
  tagWrite: true,
  entities: true,
  channels: true,
}));

const notify = vi.hoisted(() => ({ open: vi.fn() }));

const USAGE_KEYS = [
  "tags.usage.entities",
  "tags.usage.channels",
  "tags.usage.entitiesEmpty",
  "tags.usage.channelsEmpty",
] as const;

vi.mock("@refinedev/core", () => ({
  useTranslate: () => (key: string, values?: Record<string, unknown>) => {
    const template = key;
    if (!values) return template;
    return template.replace(/\{\{(\w+)\}\}/g, (_, name: string) =>
      String(values[name] ?? ""),
    );
  },
  useNotification: () => notify,
  useCan: ({ resource }: { resource: string; action: string }) => {
    if (resource === "tags") return { data: { can: access.tagWrite } };
    if (resource === "entities") return { data: { can: access.entities } };
    if (resource === "channels") return { data: { can: access.channels } };
    return { data: { can: false } };
  },
  usePermissions: () => ({ data: [] }),
  useBreadcrumb: () => ({ breadcrumbs: [] }),
  CanAccess: ({ children }: { children: ReactNode }) => children,
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
  usePathname: () => "/console/tags/tag_0123456789ab",
  useRouter: () => ({ push: vi.fn(), replace: vi.fn(), refresh: vi.fn() }),
  useSearchParams: () => new URLSearchParams(),
}));

vi.mock("@/providers/session-store", () => ({
  useSessionStore: (selector?: (state: { user: null }) => unknown) =>
    selector ? selector({ user: null }) : { user: null },
}));

vi.mock("@/features/tags/api", () => ({
  getTag: vi.fn(),
  createTag: vi.fn(),
  patchTag: vi.fn(),
  deleteTag: vi.fn(),
  listTags: vi.fn(),
}));

vi.mock("@/features/entities/api", () => ({
  listEntities: vi.fn(),
}));

vi.mock("@/features/channels/api", () => ({
  listChannels: vi.fn(),
}));

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
}

function tag(overrides: Partial<Tag> = {}): Tag {
  return {
    id: TAG_ID,
    name: "Ledger",
    description: null,
    entity_count: 2,
    channel_count: 2,
    created_at: "2026-01-01T00:00:00Z",
    updated_at: "2026-01-01T00:00:00Z",
    ...overrides,
  };
}

function entity(overrides: Partial<BusinessEntity> = {}): BusinessEntity {
  return {
    id: "ent_visible",
    table_name: "visible_row",
    name: "Visible",
    description: "",
    deprecated_at: "2026-02-01T00:00:00Z",
    ever_published: true,
    current_version: null,
    tags: [{ id: TAG_ID, name: "Ledger" }],
    tag_revision: 2,
    created_at: "2026-01-01T00:00:00Z",
    updated_at: "2026-01-01T00:00:00Z",
    ...overrides,
  };
}

function channel(overrides: Partial<Channel> = {}): Channel {
  return {
    id: "chn_quiet",
    name: "Quiet",
    description: null,
    active: false,
    draft_revision: 1,
    draft_updated_at: "2026-01-01T00:00:00Z",
    latest_version: null,
    failure_streak: 0,
    persistently_failing: false,
    tags: [{ id: TAG_ID, name: "Ledger" }],
    tag_revision: 2,
    created_at: "2026-01-01T00:00:00Z",
    updated_at: "2026-01-01T00:00:00Z",
    ...overrides,
  };
}

function fieldText(label: string): string {
  const labelNode = screen.getByText(label);
  const stack = labelNode.closest(".field-chrome__label")?.parentElement;
  return stack?.textContent ?? "";
}

async function renderTag(mode: "show" | "edit", record: Tag = tag()) {
  vi.mocked(getTag).mockResolvedValue({ tag: record });
  const { TagRecord } = await import("@/features/tags/TagRecord");
  render(
    createElement(
      MantineProvider,
      null,
      createElement(TagRecord, { mode, tagId: TAG_ID }),
    ),
  );
  await screen.findByRole("heading", { name: "Ledger" });
}

describe("Tag show usage", () => {
  beforeEach(() => {
    stubDomApis();
    access.tagWrite = true;
    access.entities = true;
    access.channels = true;
    vi.clearAllMocks();
    vi.mocked(listEntities).mockResolvedValue({
      items: [entity()],
      total: 1,
      limit: 50,
      offset: 0,
    });
    vi.mocked(listChannels).mockResolvedValue({
      items: [channel()],
      total: 1,
      limit: 50,
      offset: 0,
    });
  });

  afterEach(() => {
    cleanup();
  });

  it("lists carriers without status, active, or a saved filter", async () => {
    await renderTag("show");

    await waitFor(() => {
      expect(listEntities).toHaveBeenCalledWith({
        tag_id: [TAG_ID],
        limit: 50,
        offset: 0,
      });
    });
    expect(listChannels).toHaveBeenCalledWith({
      tag_id: [TAG_ID],
      limit: 50,
      offset: 0,
    });
    expect(await screen.findByText("Visible")).toBeTruthy();
    expect(screen.getByText("Quiet")).toBeTruthy();
    expect(screen.getByText("entities.status.deprecated")).toBeTruthy();
    expect(screen.getByText("channels.status.inactive")).toBeTruthy();
    expect(screen.getByRole("link", { name: "Visible" }).getAttribute("href")).toBe(
      "/console/entities/ent_visible",
    );
    expect(screen.getByRole("link", { name: "Quiet" }).getAttribute("href")).toBe(
      "/console/channels/chn_quiet",
    );
  });

  it("shows the detail counts when the visible lists are smaller", async () => {
    await renderTag("show", tag({ entity_count: 2, channel_count: 2 }));

    await screen.findByText("Visible");
    expect(fieldText("tags.fields.entityCount")).toContain("2");
    expect(fieldText("tags.fields.entityCount")).not.toContain("1");
    expect(fieldText("tags.fields.channelCount")).toContain("2");
    expect(fieldText("tags.fields.channelCount")).not.toContain("1");
    expect(screen.getByRole("heading", { name: "tags.usage.entities" }).textContent).toBe(
      "tags.usage.entities",
    );
    expect(screen.getByRole("heading", { name: "tags.usage.channels" }).textContent).toBe(
      "tags.usage.channels",
    );
  });

  it("omits a side the caller cannot list and still shows its count", async () => {
    access.entities = false;
    await renderTag("show", tag({ entity_count: 2, channel_count: 2 }));

    await waitFor(() => {
      expect(listChannels).toHaveBeenCalledWith({
        tag_id: [TAG_ID],
        limit: 50,
        offset: 0,
      });
    });
    expect(listEntities).not.toHaveBeenCalled();
    expect(screen.queryByRole("heading", { name: "tags.usage.entities" })).toBeNull();
    expect(screen.queryByText("Visible")).toBeNull();
    expect(fieldText("tags.fields.entityCount")).toContain("2");
    expect(screen.getByRole("heading", { name: "tags.usage.channels" })).toBeTruthy();
    expect(screen.getByText("Quiet")).toBeTruthy();
  });

  it("keeps the counts when no visible record carries the tag", async () => {
    vi.mocked(listEntities).mockResolvedValue({
      items: [],
      total: 0,
      limit: 50,
      offset: 0,
    });
    vi.mocked(listChannels).mockResolvedValue({
      items: [],
      total: 0,
      limit: 50,
      offset: 0,
    });
    await renderTag("show", tag({ entity_count: 2, channel_count: 3 }));
    expect(await screen.findByText("tags.usage.entitiesEmpty")).toBeTruthy();
    expect(screen.getByText("tags.usage.channelsEmpty")).toBeTruthy();
    expect(fieldText("tags.fields.entityCount")).toContain("2");
    expect(fieldText("tags.fields.channelCount")).toContain("3");
    expect(fieldText("tags.fields.channelCount")).not.toContain("0");
  });

  it("does not load usage lists on edit", async () => {
    await renderTag("edit");
    expect(listEntities).not.toHaveBeenCalled();
    expect(listChannels).not.toHaveBeenCalled();
    expect(screen.queryByRole("heading", { name: "tags.usage.entities" })).toBeNull();
    expect(fieldText("tags.fields.entityCount")).toContain("2");
  });

  it("has English and Chinese usage copy", () => {
    const english = en as Record<string, string>;
    const chinese = zh as Record<string, string>;
    for (const key of USAGE_KEYS) {
      expect(english[key], key).toEqual(expect.any(String));
      expect(chinese[key], key).toEqual(expect.any(String));
      expect(english[key].length).toBeGreaterThan(0);
      expect(chinese[key].length).toBeGreaterThan(0);
      expect(chinese[key]).not.toBe(english[key]);
    }
  });
});
