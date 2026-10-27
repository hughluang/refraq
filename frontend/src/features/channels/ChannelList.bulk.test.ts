/** @vitest-environment jsdom */

import { MantineProvider } from "@mantine/core";
import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { createElement, type ReactNode } from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { addChannelTags, listChannels } from "@/features/channels/api";
import type { Channel } from "@/features/channels/types";
import { listTags } from "@/features/tags/api";
import { ApiError } from "@/lib/api";

const flags = vi.hoisted(() => ({ canWrite: true }));
const notify = vi.hoisted(() => vi.fn());

const LABELS: Record<string, string> = {
  "channels.title": "Data Channels",
  "channels.description": "Flows",
  "channels.create": "Create",
  "channels.search": "Search channels",
  "channels.fields.name": "Name",
  "channels.fields.tags": "Tags",
  "channels.fields.active": "Active",
  "channels.fields.latestVersion": "Latest version",
  "channels.fields.updatedAt": "Updated",
  "channels.list.empty": "Empty",
  "channels.list.noMatch": "No match",
  "channels.list.tagFilter": "Tag filter",
  "channels.list.tagNone": "No matching tags",
  "channels.list.activation": "Activation",
  "channels.status.active": "Active",
  "channels.status.inactive": "Inactive",
  "channels.bulk.select": "Select {{name}}",
  "channels.bulk.selectPage": "Select rows on this page",
  "channels.bulk.add": "Add tags",
  "channels.bulk.remove": "Remove tags",
  "channels.bulk.addTitle": "Add tags",
  "channels.bulk.addBody": "Add these tags to the checked rows.",
  "channels.bulk.tags": "Tags",
  "channels.bulk.confirmAdd": "Add tags",
  "common.cancel": "Cancel",
  "common.list.search": "Search",
  "common.showing": "{{from}}-{{to}} of {{total}}",
  "savedFilters.list": "Saved filters",
  "savedFilters.placeholder": "Saved filter",
  "savedFilters.name": "Filter name",
  "savedFilters.save": "Save filter",
  "problems.TAG_LIMIT_EXCEEDED": "A record can carry at most ten Tags.",
  "problems.unknown": "Something went wrong. Try again.",
  "tags.bulk.wroteNothing": "None of the checked rows were changed.",
  "tags.bulk.nameSeparator": ", ",
  "tags.bulk.refused": "{{lead}} {{unchanged}}",
  "tags.bulk.refusedNamed": "{{lead}} {{names}}. {{unchanged}}",
};

vi.mock("@refinedev/core", () => ({
  useTranslate: () => (key: string, values?: Record<string, unknown>) => {
    const template = LABELS[key] ?? key;
    if (!values) return template;
    return template.replace(/\{\{(\w+)\}\}/g, (_, name: string) =>
      String(values[name] ?? ""),
    );
  },
  useNotification: () => ({ open: notify }),
  useCan: () => ({ data: { can: flags.canWrite } }),
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
  usePathname: () => "/console/channels",
  useRouter: () => ({ push: vi.fn(), replace: vi.fn(), refresh: vi.fn() }),
  useSearchParams: () => new URLSearchParams(),
}));

vi.mock("@/hooks/useFormatInstant", () => ({
  useShowInstant: () => (value: string) => value,
}));

vi.mock("@/features/channels/api", () => ({
  listChannels: vi.fn(),
  addChannelTags: vi.fn(async () => ({ subjects: [] })),
  removeChannelTags: vi.fn(async () => ({ subjects: [] })),
}));

vi.mock("@/features/tags/api", () => ({
  listTags: vi.fn(async () => ({ items: [], total: 0, limit: 8, offset: 0 })),
}));

vi.mock("@/features/channels/channelListFilter", async () => {
  const actual = await vi.importActual<typeof import("@/features/channels/channelListFilter")>(
    "@/features/channels/channelListFilter",
  );
  return {
    ...actual,
    loadChannelSavedFilters: vi.fn(async () => ({ filters: [], rememberedId: null })),
    rememberChannelSavedFilter: vi.fn(),
    createChannelSavedFilter: vi.fn(),
    patchChannelSavedFilter: vi.fn(),
  };
});

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

function channelRow(id: string, name: string): Channel {
  return {
    id,
    name,
    description: null,
    active: false,
    draft_revision: 1,
    draft_updated_at: "2026-09-10T04:00:00Z",
    latest_version: null,
    failure_streak: 0,
    persistently_failing: false,
    tags: [],
    tag_revision: 1,
    created_at: "2026-09-10T04:00:00Z",
    updated_at: "2026-09-10T04:00:00Z",
  };
}

function pageOf(names: string[], total: number, offset: number) {
  return {
    items: names.map((name, index) => channelRow(`chn_${offset + index}`, name)),
    total,
    limit: 50,
    offset,
  };
}

async function renderList() {
  const { ChannelList } = await import("@/features/channels/ChannelList");
  render(createElement(MantineProvider, null, createElement(ChannelList)));
  await screen.findByRole("checkbox", { name: "Select rows on this page" });
}

function chooseOption(comboboxName: string, optionName: string) {
  fireEvent.mouseDown(screen.getByRole("combobox", { name: comboboxName }));
  const lists = screen.getAllByRole("listbox", { hidden: true });
  const list = lists.find((item) =>
    within(item).queryByRole("option", { name: optionName, hidden: true }),
  );
  if (!list) throw new Error(`no listbox for ${optionName}`);
  const option = within(list).getByRole("option", { name: optionName, hidden: true });
  fireEvent.mouseDown(option);
  fireEvent.click(option);
}

async function pickLedger() {
  vi.mocked(listTags).mockImplementation(async (params) => {
    if (!params?.q) return { items: [], total: 0, limit: 8, offset: 0 };
    return {
      items: [
        {
          id: "tag_ledger",
          name: "Ledger",
          description: null,
          created_at: "2026-09-10T04:00:00Z",
          updated_at: "2026-09-10T04:00:00Z",
        },
      ],
      total: 1,
      limit: 8,
      offset: 0,
    };
  });
  const dialog = await screen.findByRole("dialog");
  const input = within(dialog).getByRole("combobox", { name: "Tags" });
  input.focus();
  fireEvent.change(input, { target: { value: "Led" } });
  const option = await screen.findByRole("option", { name: "Ledger", hidden: true });
  fireEvent.mouseDown(option);
  fireEvent.click(option);
  const confirm = within(dialog).getByRole("button", { name: "Add tags" });
  await waitFor(() => {
    expect((confirm as HTMLButtonElement).disabled).toBe(false);
  });
  fireEvent.click(confirm);
}

describe("ChannelList bulk tags", () => {
  beforeEach(() => {
    stubDomApis();
    flags.canWrite = true;
    notify.mockClear();
    vi.clearAllMocks();
    vi.mocked(listChannels).mockImplementation(async (params) => {
      const offset = params?.offset ?? 0;
      if (offset > 0) return pageOf(["Second"], 2, offset);
      return pageOf(["Alpha", "Beta"], 2, 0);
    });
  });

  afterEach(() => {
    cleanup();
  });

  it("sends only the checked ids on the current page", async () => {
    await renderList();
    fireEvent.click(screen.getByRole("checkbox", { name: "Select Alpha" }));
    fireEvent.click(screen.getByRole("button", { name: "Add tags" }));
    await pickLedger();
    await waitFor(() => {
      expect(addChannelTags).toHaveBeenCalledWith({
        channel_ids: ["chn_0"],
        tag_ids: ["tag_ledger"],
      });
    });
  });

  it("clears checks when the page changes, so the next request omits the earlier row", async () => {
    vi.mocked(listChannels).mockImplementation(async (params) => {
      const offset = params?.offset ?? 0;
      if (offset > 0) return pageOf(["Second"], 51, offset);
      return pageOf(
        Array.from({ length: 50 }, (_, index) => `Row ${index}`),
        51,
        0,
      );
    });
    await renderList();
    fireEvent.click(screen.getByRole("checkbox", { name: "Select Row 0" }));
    fireEvent.click(screen.getByRole("button", { name: "2", exact: true }));
    await screen.findByRole("checkbox", { name: "Select Second" });
    expect(
      (screen.getByRole("checkbox", { name: "Select Second" }) as HTMLInputElement).checked,
    ).toBe(false);
    expect(screen.queryByRole("checkbox", { name: "Select Row 0" })).toBeNull();
    fireEvent.click(screen.getByRole("checkbox", { name: "Select Second" }));
    fireEvent.click(screen.getByRole("button", { name: "Add tags" }));
    await pickLedger();
    await waitFor(() => {
      expect(addChannelTags).toHaveBeenCalledWith({
        channel_ids: ["chn_50"],
        tag_ids: ["tag_ledger"],
      });
    });
  });

  it("clears checks when the activation filter changes", async () => {
    await renderList();
    fireEvent.click(screen.getByRole("checkbox", { name: "Select Alpha" }));
    expect(
      (screen.getByRole("checkbox", { name: "Select Alpha" }) as HTMLInputElement).checked,
    ).toBe(true);
    chooseOption("Activation", "Active");
    await waitFor(() => {
      expect(
        (screen.getByRole("checkbox", { name: "Select Alpha" }) as HTMLInputElement).checked,
      ).toBe(false);
    });
    expect(
      (screen.getByRole("button", { name: "Add tags" }) as HTMLButtonElement).disabled,
    ).toBe(true);
  });

  it("names the row that would pass ten tags and leaves the checked rows unchanged", async () => {
    vi.mocked(addChannelTags).mockRejectedValueOnce(
      new ApiError(422, "TAG_LIMIT_EXCEEDED", "A record can carry at most ten Tags", null, {
        subjects: [{ kind: "channel", id: "chn_0" }],
      }),
    );
    await renderList();
    const fetches = vi.mocked(listChannels).mock.calls.length;
    fireEvent.click(screen.getByRole("checkbox", { name: "Select Alpha" }));
    fireEvent.click(screen.getByRole("checkbox", { name: "Select Beta" }));
    fireEvent.click(screen.getByRole("button", { name: "Add tags" }));
    await pickLedger();
    await waitFor(() => {
      expect(notify).toHaveBeenCalledWith(
        expect.objectContaining({
          type: "error",
          message:
            "A record can carry at most ten Tags. Alpha. None of the checked rows were changed.",
        }),
      );
    });
    expect(vi.mocked(listChannels).mock.calls.length).toBe(fetches);
    expect(screen.getByRole("dialog")).toBeTruthy();
    expect(
      (screen.getByRole("checkbox", { name: "Select Alpha" }) as HTMLInputElement).checked,
    ).toBe(true);
    expect(
      (screen.getByRole("checkbox", { name: "Select Beta" }) as HTMLInputElement).checked,
    ).toBe(true);
  });

  it("hides the selection and the bulk actions from a read-only caller", async () => {
    flags.canWrite = false;
    const { ChannelList } = await import("@/features/channels/ChannelList");
    render(createElement(MantineProvider, null, createElement(ChannelList)));
    await screen.findByText("Alpha");
    expect(screen.queryByRole("checkbox")).toBeNull();
    expect(screen.queryByRole("button", { name: "Add tags" })).toBeNull();
    expect(screen.queryByRole("button", { name: "Remove tags" })).toBeNull();
  });
});
