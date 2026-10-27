/** @vitest-environment jsdom */

import { MantineProvider } from "@mantine/core";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { createElement, type ReactNode } from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import {
  createEntity,
  getEntity,
  getVersion,
  listVersions,
  patchEntity,
  replaceEntityTags,
} from "@/features/entities/api";
import { listTags } from "@/features/tags/api";
import type { BusinessEntity, EntityVersion } from "@/features/entities/types";

const flags = vi.hoisted(() => ({ canWrite: true }));

const LABELS: Record<string, string> = {
  "entities.title": "Business Entities",
  "entities.create.title": "Create Business Entity",
  "entities.create.submit": "Save",
  "entities.edit.submit": "Save",
  "entities.publish": "Publish",
  "entities.versions.open": "Open new version",
  "entities.fields.tableName": "Table name",
  "entities.fields.name": "Name",
  "entities.fields.description": "Description",
  "entities.validation.required": "Required",
  "entities.tags.title": "Tags",
  "entities.tags.description": "Tags organize this Entity. Saving them does not change the definition.",
  "entities.tags.createDescription": "Tags organize this Entity. They are submitted with this save.",
  "entities.tags.field": "Add a tag",
  "entities.tags.save": "Save tags",
  "entities.tags.empty": "No tags",
  "entities.tags.remove": "Remove {{name}}",
  "entities.tabs.overview": "Overview",
  "entities.tabs.attributes": "Attributes",
  "entities.tabs.versions": "Versions",
  "common.cancel": "Cancel",
};

vi.mock("@refinedev/core", () => ({
  useTranslate: () => (key: string, values?: Record<string, unknown>) => {
    const template = LABELS[key] ?? key;
    if (!values) return template;
    return template.replace(/\{\{(\w+)\}\}/g, (_, name: string) =>
      String(values[name] ?? ""),
    );
  },
  useNotification: () => ({ open: vi.fn() }),
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

vi.mock("@/features/entities/api", () => ({
  getEntity: vi.fn(),
  listVersions: vi.fn(),
  getVersion: vi.fn(),
  publishVersion: vi.fn(),
  previewEntityPublish: vi.fn(async () => ({ incompatible_write_nodes: [] })),
  deprecateEntity: vi.fn(),
  createEntity: vi.fn(),
  deleteEntity: vi.fn(),
  enqueueDropTable: vi.fn(),
  openVersion: vi.fn(),
  patchEntity: vi.fn(),
  replaceEntityTags: vi.fn(),
}));

vi.mock("@/features/tags/api", () => ({
  listTags: vi.fn(async () => ({ items: [], total: 0, limit: 8, offset: 0 })),
}));

vi.mock("@/features/entities/EntityOverviewTab", () => ({
  EntityOverviewTab: () => createElement("div", null, "overview"),
}));

vi.mock("@/features/entities/EntityAttributesTab", () => ({
  EntityAttributesTab: () => createElement("div", null, "attributes"),
}));

vi.mock("@/features/entities/EntityVersionsTab", () => ({
  EntityVersionsTab: () => createElement("div", null, "versions"),
}));

vi.mock("@/features/jobs/JobDetailModal", () => ({
  JobDetailModal: () => null,
}));

vi.mock("@/providers/session-store", () => ({
  useSessionStore: () => null,
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

function entity(overrides: Partial<BusinessEntity> = {}): BusinessEntity {
  return {
    id: "ent_1",
    table_name: "material",
    name: "Material",
    description: "x",
    deprecated_at: null,
    ever_published: false,
    current_version: {
      id: "encv_1",
      version: 1,
      publish_status: "unpublished",
      table_name: null,
      alignment: {
        table_present: false,
        latest_job_id: null,
        latest_job_status: null,
      },
    },
    created_at: "2026-09-10T04:00:00Z",
    updated_at: "2026-09-10T04:00:00Z",
    tags: [],
    tag_revision: 1,
    ...overrides,
  };
}

function versionFor(record: BusinessEntity): EntityVersion {
  const current = record.current_version!;
  return {
    id: current.id,
    entity_id: record.id,
    version: current.version,
    publish_status: current.publish_status,
    attributes: [
      {
        name: "sku",
        type: "string",
        required: true,
        unique: true,
        indexed: false,
        business_key: false,
        description: null,
        config: { max_length: 64 },
      },
    ],
    attribute_count: 1,
    table_name: current.table_name,
    alignment: current.alignment,
    created_at: "2026-09-10T04:00:00Z",
    updated_at: "2026-09-10T04:00:00Z",
  };
}

function button(name: string) {
  return screen.getByRole("button", {
    name: (value) => value === name,
  }) as HTMLButtonElement;
}

async function renderRecord(
  record: BusinessEntity,
  mode: "show" | "edit" = "show",
) {
  vi.mocked(getEntity).mockResolvedValue({ entity: record });
  vi.mocked(listVersions).mockResolvedValue({
    items: [versionFor(record)],
    total: 1,
    limit: 200,
    offset: 0,
  });
  vi.mocked(getVersion).mockResolvedValue({ version: versionFor(record) });
  const { EntityRecord } = await import("@/features/entities/EntityRecord");
  render(
    createElement(
      MantineProvider,
      null,
      createElement(EntityRecord, { mode, entityId: record.id }),
    ),
  );
  await screen.findByText("Material · material");
}

describe("EntityRecord tags", () => {
  beforeEach(() => {
    stubDomApis();
    flags.canWrite = true;
    vi.clearAllMocks();
    vi.mocked(listTags).mockResolvedValue({ items: [], total: 0, limit: 8, offset: 0 });
    vi.mocked(replaceEntityTags).mockResolvedValue({
      tags: [{ id: "tag_ledger", name: "Ledger" }],
      tag_revision: 2,
    });
  });

  afterEach(() => {
    cleanup();
  });

  it("saves show-page tags through PUT and leaves Publish enabled", async () => {
    vi.mocked(listTags).mockResolvedValue({
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
    });
    await renderRecord(entity());

    fireEvent.change(screen.getByRole("textbox", { name: "Add a tag" }), {
      target: { value: "Ledger" },
    });
    fireEvent.click(await screen.findByRole("button", { name: (value) => value === "Ledger" }));

    expect(button("Publish").disabled).toBe(false);
    fireEvent.click(button("Save tags"));
    await waitFor(() => {
      expect(replaceEntityTags).toHaveBeenCalledWith("ent_1", {
        base_revision: 1,
        tag_ids: ["tag_ledger"],
        names: [],
      });
    });
    expect(patchEntity).not.toHaveBeenCalled();
    expect(button("Publish").disabled).toBe(false);
  });

  it("keeps Open new version enabled while a published entity's tags change", async () => {
    await renderRecord(
      entity({
        ever_published: true,
        current_version: {
          id: "encv_1",
          version: 1,
          publish_status: "published",
          table_name: "material",
          alignment: {
            table_present: true,
            latest_job_id: "job_1",
            latest_job_status: "succeeded",
          },
        },
      }),
    );

    const field = screen.getByRole("textbox", { name: "Add a tag" });
    fireEvent.change(field, { target: { value: "Books" } });
    fireEvent.keyDown(field, { key: "Enter" });

    expect(button("Open new version").disabled).toBe(false);
    fireEvent.click(button("Save tags"));
    await waitFor(() => {
      expect(replaceEntityTags).toHaveBeenCalledWith("ent_1", {
        base_revision: 1,
        tag_ids: [],
        names: ["Books"],
      });
    });
    expect(patchEntity).not.toHaveBeenCalled();
  });

  it("shows tags without an editor when the entity is deprecated", async () => {
    await renderRecord(
      entity({
        deprecated_at: "2026-09-11T00:00:00Z",
        ever_published: true,
        tags: [{ id: "tag_ledger", name: "Ledger" }],
        current_version: {
          id: "encv_1",
          version: 1,
          publish_status: "published",
          table_name: "material",
          alignment: {
            table_present: true,
            latest_job_id: "job_1",
            latest_job_status: "succeeded",
          },
        },
      }),
    );

    expect(screen.getByText("Ledger")).toBeTruthy();
    expect(screen.queryByRole("textbox", { name: "Add a tag" })).toBeNull();
    expect(screen.queryByRole("button", { name: (value) => value === "Save tags" })).toBeNull();
  });

  it("shows tags without an editor when the operator cannot write entities", async () => {
    flags.canWrite = false;
    await renderRecord(entity());

    expect(screen.getByText("No tags")).toBeTruthy();
    expect(screen.queryByRole("textbox", { name: "Add a tag" })).toBeNull();
    expect(screen.queryByRole("button", { name: (value) => value === "Save tags" })).toBeNull();
  });

  it("saves edit-page tags through PUT and leaves them off the definition save", async () => {
    vi.mocked(patchEntity).mockResolvedValue({ entity: entity() });
    await renderRecord(entity(), "edit");

    const field = screen.getByRole("textbox", { name: "Add a tag" });
    fireEvent.change(field, { target: { value: "Books" } });
    fireEvent.keyDown(field, { key: "Enter" });
    expect(patchEntity).not.toHaveBeenCalled();

    fireEvent.click(button("Save tags"));
    await waitFor(() => {
      expect(replaceEntityTags).toHaveBeenCalledWith("ent_1", {
        base_revision: 1,
        tag_ids: [],
        names: ["Books"],
      });
    });

    fireEvent.click(button("Save"));
    await waitFor(() => {
      expect(patchEntity).toHaveBeenCalled();
    });
    const body = vi.mocked(patchEntity).mock.calls[0]?.[1];
    expect(body).not.toHaveProperty("tags");
  });

  it("keeps an unsaved tag name when a definition save returns the same assignment", async () => {
    const record = entity();
    vi.mocked(patchEntity).mockResolvedValue({ entity: record });
    await renderRecord(record, "edit");

    const field = screen.getByRole("textbox", { name: "Add a tag" });
    fireEvent.change(field, { target: { value: "Books" } });
    fireEvent.keyDown(field, { key: "Enter" });
    expect(screen.getByRole("button", { name: "Remove Books" })).toBeTruthy();

    vi.mocked(getEntity).mockImplementation(async () => ({
      entity: {
        ...record,
        tags: record.tags.map((tag) => ({ id: tag.id, name: tag.name })),
      },
    }));
    fireEvent.click(button("Save"));
    await waitFor(() => {
      expect(patchEntity).toHaveBeenCalled();
      expect(getEntity.mock.calls.length).toBeGreaterThan(1);
    });
    expect(screen.getByRole("button", { name: "Remove Books" })).toBeTruthy();
    expect(replaceEntityTags).not.toHaveBeenCalled();
    const body = vi.mocked(patchEntity).mock.calls[0]?.[1];
    expect(body).not.toHaveProperty("tags");
  });

  it("sends the tag field text when save tags is clicked without Enter", async () => {
    await renderRecord(entity(), "edit");

    fireEvent.change(screen.getByRole("textbox", { name: "Add a tag" }), {
      target: { value: "Books" },
    });
    fireEvent.click(button("Save tags"));

    await waitFor(() => {
      expect(replaceEntityTags).toHaveBeenCalledWith("ent_1", {
        base_revision: 1,
        tag_ids: [],
        names: ["Books"],
      });
    });
  });

  it("sends committed tag names with the create body", async () => {
    vi.mocked(createEntity).mockImplementation(() => new Promise(() => {}));
    const { EntityRecord } = await import("@/features/entities/EntityRecord");
    render(
      createElement(MantineProvider, null, createElement(EntityRecord, { mode: "create" })),
    );
    await screen.findByRole("textbox", { name: "Table name" });

    fireEvent.change(screen.getByRole("textbox", { name: "Table name" }), {
      target: { value: "material" },
    });
    fireEvent.change(screen.getByRole("textbox", { name: "Name" }), {
      target: { value: "Material" },
    });
    fireEvent.change(screen.getByRole("textbox", { name: "Description" }), {
      target: { value: "A material" },
    });
    const field = screen.getByRole("textbox", { name: "Add a tag" });
    fireEvent.change(field, { target: { value: "Ledger" } });
    fireEvent.keyDown(field, { key: "Enter" });
    fireEvent.click(button("Save"));

    await waitFor(() => {
      expect(createEntity).toHaveBeenCalledWith(
        expect.objectContaining({
          table_name: "material",
          name: "Material",
          description: "A material",
          tags: { tag_ids: [], names: ["Ledger"] },
        }),
      );
    });
    expect(replaceEntityTags).not.toHaveBeenCalled();
  });

  it("sends the tag field text with the create body without Enter", async () => {
    vi.mocked(createEntity).mockImplementation(() => new Promise(() => {}));
    const { EntityRecord } = await import("@/features/entities/EntityRecord");
    render(
      createElement(MantineProvider, null, createElement(EntityRecord, { mode: "create" })),
    );
    await screen.findByRole("textbox", { name: "Table name" });

    fireEvent.change(screen.getByRole("textbox", { name: "Table name" }), {
      target: { value: "material" },
    });
    fireEvent.change(screen.getByRole("textbox", { name: "Name" }), {
      target: { value: "Material" },
    });
    fireEvent.change(screen.getByRole("textbox", { name: "Description" }), {
      target: { value: "A material" },
    });
    fireEvent.change(screen.getByRole("textbox", { name: "Add a tag" }), {
      target: { value: "Ledger" },
    });
    expect(
      screen.getByText("Tags organize this Entity. They are submitted with this save."),
    ).toBeTruthy();
    expect(screen.queryByRole("button", { name: (value) => value === "Save tags" })).toBeNull();
    fireEvent.click(button("Save"));

    await waitFor(() => {
      expect(createEntity).toHaveBeenCalledWith(
        expect.objectContaining({
          tags: { tag_ids: [], names: ["Ledger"] },
        }),
      );
    });
    expect(replaceEntityTags).not.toHaveBeenCalled();
  });
});
