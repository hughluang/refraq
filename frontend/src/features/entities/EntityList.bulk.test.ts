/** @vitest-environment jsdom */

import { MantineProvider } from "@mantine/core";
import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { createElement, type ReactNode } from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { addEntityTags, listEntities } from "@/features/entities/api";
import type { BusinessEntity } from "@/features/entities/types";
import { listTags } from "@/features/tags/api";

const flags = vi.hoisted(() => ({ canWrite: true }));
const notify = vi.hoisted(() => vi.fn());

const LABELS: Record<string, string> = {
  "entities.title": "Business Entities",
  "entities.description": "Definitions",
  "entities.create": "Create",
  "entities.search": "Search entities",
  "entities.fields.name": "Name",
  "entities.fields.tags": "Tags",
  "entities.fields.version": "Version",
  "entities.fields.entityStatus": "Entity status",
  "entities.fields.versionStatus": "Version status",
  "entities.fields.updatedAt": "Updated",
  "entities.status.notServing": "Not serving",
  "entities.status.serving": "Serving",
  "entities.status.deprecated": "Deprecated",
  "entities.list.empty": "Empty",
  "entities.list.noMatch": "No match",
  "entities.list.tagFilter": "Tag filter",
  "entities.list.tagNone": "No matching tags",
  "entities.bulk.select": "Select {{name}}",
  "entities.bulk.selectPage": "Select rows on this page",
  "entities.bulk.add": "Add tags",
  "entities.bulk.remove": "Remove tags",
  "entities.bulk.addTitle": "Add tags",
  "entities.bulk.removeTitle": "Remove tags",
  "entities.bulk.addBody": "Add these tags to the checked rows.",
  "entities.bulk.removeBody": "Remove these tags from the checked rows.",
  "entities.bulk.tags": "Tags",
  "entities.bulk.confirmAdd": "Add tags",
  "entities.bulk.confirmRemove": "Remove tags",
  "common.cancel": "Cancel",
  "common.list.search": "Search",
  "common.showing": "{{from}}-{{to}} of {{total}}",
  "savedFilters.list": "Saved filters",
  "savedFilters.placeholder": "Saved filter",
  "savedFilters.name": "Filter name",
  "savedFilters.save": "Save filter",
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
  usePathname: () => "/console/entities",
  useRouter: () => ({ push: vi.fn(), replace: vi.fn(), refresh: vi.fn() }),
  useSearchParams: () => new URLSearchParams(),
}));

vi.mock("@/hooks/useFormatInstant", () => ({
  useShowInstant: () => (value: string) => value,
}));

vi.mock("@/features/entities/api", () => ({
  listEntities: vi.fn(),
  addEntityTags: vi.fn(async () => ({ subjects: [] })),
  removeEntityTags: vi.fn(async () => ({ subjects: [] })),
}));

vi.mock("@/features/tags/api", () => ({
  listTags: vi.fn(async () => ({ items: [], total: 0, limit: 8, offset: 0 })),
}));

vi.mock("@/features/entities/entityListFilter", async () => {
  const actual = await vi.importActual<typeof import("@/features/entities/entityListFilter")>(
    "@/features/entities/entityListFilter",
  );
  return {
    ...actual,
    loadEntitySavedFilters: vi.fn(async () => ({ filters: [], rememberedId: null })),
    rememberEntitySavedFilter: vi.fn(),
    createEntitySavedFilter: vi.fn(),
    patchEntitySavedFilter: vi.fn(),
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

function entityRow(id: string, name: string): BusinessEntity {
  return {
    id,
    table_name: id,
    name,
    description: "x",
    deprecated_at: null,
    ever_published: false,
    current_version: {
      id: `${id}_v`,
      version: 1,
      publish_status: "unpublished",
      table_name: null,
      alignment: {
        table_present: false,
        latest_job_id: null,
        latest_job_status: null,
      },
    },
    tags: [],
    tag_revision: 1,
    created_at: "2026-09-10T04:00:00Z",
    updated_at: "2026-09-10T04:00:00Z",
  };
}

function pageOf(names: string[], total: number, offset: number) {
  return {
    items: names.map((name, index) => entityRow(`ent_${offset + index}`, name)),
    total,
    limit: 50,
    offset,
  };
}

async function renderList() {
  const { EntityList } = await import("@/features/entities/EntityList");
  render(createElement(MantineProvider, null, createElement(EntityList)));
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

describe("EntityList bulk tags", () => {
  beforeEach(() => {
    stubDomApis();
    flags.canWrite = true;
    notify.mockClear();
    vi.clearAllMocks();
    vi.mocked(listEntities).mockImplementation(async (params) => {
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
      expect(addEntityTags).toHaveBeenCalledWith({
        entity_ids: ["ent_0"],
        tag_ids: ["tag_ledger"],
      });
    });
  });

  it("clears checks when the page changes, so the next request omits the earlier row", async () => {
    vi.mocked(listEntities).mockImplementation(async (params) => {
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
      expect(addEntityTags).toHaveBeenCalledWith({
        entity_ids: ["ent_50"],
        tag_ids: ["tag_ledger"],
      });
    });
  });

  it("clears checks when the status filter changes", async () => {
    await renderList();
    fireEvent.click(screen.getByRole("checkbox", { name: "Select Alpha" }));
    expect(
      (screen.getByRole("checkbox", { name: "Select Alpha" }) as HTMLInputElement).checked,
    ).toBe(true);
    chooseOption("Entity status", "Deprecated");
    await waitFor(() => {
      expect(
        (screen.getByRole("checkbox", { name: "Select Alpha" }) as HTMLInputElement).checked,
      ).toBe(false);
    });
    expect(
      (screen.getByRole("button", { name: "Add tags" }) as HTMLButtonElement).disabled,
    ).toBe(true);
  });

  it("hides the selection and the bulk actions from a read-only caller", async () => {
    flags.canWrite = false;
    const { EntityList } = await import("@/features/entities/EntityList");
    render(createElement(MantineProvider, null, createElement(EntityList)));
    await screen.findByText("Alpha");
    expect(screen.queryByRole("checkbox")).toBeNull();
    expect(screen.queryByRole("button", { name: "Add tags" })).toBeNull();
    expect(screen.queryByRole("button", { name: "Remove tags" })).toBeNull();
  });
});
