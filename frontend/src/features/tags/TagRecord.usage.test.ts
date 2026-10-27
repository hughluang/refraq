/** @vitest-environment jsdom */

import { MantineProvider } from "@mantine/core";
import { cleanup, render, screen, waitFor } from "@testing-library/react";
import { createElement, type ReactNode } from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { getTag, listTagSubjects } from "@/features/tags/api";
import type { Tag, TagSubject } from "@/features/tags/types";
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
  "tags.usage.title",
  "tags.usage.kind",
  "tags.usage.kind.entity",
  "tags.usage.kind.channel",
  "tags.usage.name",
  "tags.usage.status",
  "tags.usage.empty",
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
  listTagSubjects: vi.fn(),
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

function subjects(): TagSubject[] {
  return [
    {
      kind: "entity",
      id: "ent_visible",
      name: "Visible",
      table_name: "visible_row",
      deprecated_at: "2026-02-01T00:00:00Z",
      ever_published: true,
    },
    {
      kind: "channel",
      id: "chn_quiet",
      name: "Quiet",
      active: false,
    },
  ];
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
    vi.mocked(listTagSubjects).mockResolvedValue({
      items: subjects(),
      total: 2,
      limit: 50,
      offset: 0,
    });
  });

  afterEach(() => {
    cleanup();
  });

  it("lists carriers in one table", async () => {
    await renderTag("show");

    await waitFor(() => {
      expect(listTagSubjects).toHaveBeenCalledWith(TAG_ID, {
        limit: 50,
        offset: 0,
      });
    });
    expect(await screen.findByText("Visible")).toBeTruthy();
    expect(screen.getByText("Quiet")).toBeTruthy();
    expect(screen.getByText("tags.usage.kind.entity")).toBeTruthy();
    expect(screen.getByText("tags.usage.kind.channel")).toBeTruthy();
    expect(screen.getByText("visible_row")).toBeTruthy();
    expect(screen.getByText("entities.status.deprecated")).toBeTruthy();
    expect(screen.getByText("channels.status.inactive")).toBeTruthy();
    expect(screen.getByRole("link", { name: "Visible" }).getAttribute("href")).toBe(
      "/console/entities/ent_visible",
    );
    expect(screen.getByRole("link", { name: "Quiet" }).getAttribute("href")).toBe(
      "/console/channels/chn_quiet",
    );
    expect(screen.getByRole("heading", { name: "tags.usage.title" })).toBeTruthy();
    expect(screen.queryByText("tags.fields.entityCount")).toBeNull();
    expect(screen.queryByText("tags.fields.channelCount")).toBeNull();
  });

  it("renders the subject page the server returned when one side is hidden", async () => {
    access.entities = false;
    vi.mocked(listTagSubjects).mockResolvedValue({
      items: [subjects()[1]],
      total: 1,
      limit: 50,
      offset: 0,
    });
    await renderTag("show");

    await waitFor(() => {
      expect(listTagSubjects).toHaveBeenCalledWith(TAG_ID, {
        limit: 50,
        offset: 0,
      });
    });
    expect(screen.queryByText("Visible")).toBeNull();
    expect(screen.getByText("Quiet")).toBeTruthy();
    expect(screen.queryByText("tags.fields.entityCount")).toBeNull();
  });

  it("uses one empty line when nothing visible carries the tag", async () => {
    vi.mocked(listTagSubjects).mockResolvedValue({
      items: [],
      total: 0,
      limit: 50,
      offset: 0,
    });
    await renderTag("show", tag({ entity_count: 2, channel_count: 3 }));
    expect(await screen.findByText("tags.usage.empty")).toBeTruthy();
    expect(screen.queryByText("tags.fields.entityCount")).toBeNull();
    expect(screen.queryByText("tags.fields.channelCount")).toBeNull();
  });

  it("uses the entity empty line when channels cannot be listed", async () => {
    access.channels = false;
    vi.mocked(listTagSubjects).mockResolvedValue({
      items: [],
      total: 0,
      limit: 50,
      offset: 0,
    });
    await renderTag("show");
    expect(await screen.findByText("tags.usage.entitiesEmpty")).toBeTruthy();
  });

  it("does not load subjects on edit or without either list permission", async () => {
    await renderTag("edit");
    expect(listTagSubjects).not.toHaveBeenCalled();
    expect(screen.queryByRole("heading", { name: "tags.usage.title" })).toBeNull();
    cleanup();

    access.entities = false;
    access.channels = false;
    await renderTag("show");
    expect(listTagSubjects).not.toHaveBeenCalled();
    expect(screen.queryByRole("heading", { name: "tags.usage.title" })).toBeNull();
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
