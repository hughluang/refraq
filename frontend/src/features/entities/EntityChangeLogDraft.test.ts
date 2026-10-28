/** @vitest-environment jsdom */

import { MantineProvider } from "@mantine/core";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { createElement, type ReactNode } from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const writePermission = vi.hoisted(() => ({ can: true }));

import {
  createEntity,
  getEntity,
  getVersion,
  listVersions,
  patchEntity,
  publishVersion,
} from "@/features/entities/api";
import type { BusinessEntity, EntityVersion } from "@/features/entities/types";

const LABELS: Record<string, string> = {
  "entities.title": "Business Entities",
  "entities.description": "Definitions",
  "entities.edit.title": "Edit entity",
  "entities.backToList": "Back",
  "entities.actions.navigation": "Navigation",
  "entities.actions.lifecycle": "Lifecycle",
  "entities.actions.standard": "Standard",
  "entities.tabs.overview": "Overview",
  "entities.tabs.attributes": "Attributes",
  "entities.tabs.versions": "Versions",
  "entities.status.notServing": "Not in service",
  "form.value.yes": "Yes",
  "form.value.no": "No",
  "entities.fields.tableName": "Table name",
  "entities.fields.name": "Name",
  "entities.fields.description": "Description",
  "entities.fields.changeLogEnabled": "Record changes",
  "entities.fields.changeLogRetentionDays": "Retention (days)",
  "entities.fields.changeLogRetentionNever": "Never expire",
  "entities.edit.submit": "Save",
  "entities.create.title": "Create Business Entity",
  "entities.create.submit": "Save",
  "jobs.refresh": "Refresh",
  "actions.edit": "Edit",
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
  useCan: () => ({ data: { can: writePermission.can } }),
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

function unpublishedEntity(): BusinessEntity {
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
  };
}

function versionFor(
  entity: BusinessEntity,
  changeLog: { enabled: boolean; retentionDays: number | null },
): EntityVersion {
  const current = entity.current_version!;
  return {
    id: current.id,
    entity_id: entity.id,
    version: current.version,
    publish_status: current.publish_status,
    attributes: [],
    attribute_count: 0,
    table_name: current.table_name,
    alignment: current.alignment,
    change_log_enabled: changeLog.enabled,
    change_log_retention_days: changeLog.retentionDays,
    created_at: "2026-09-10T04:00:00Z",
    updated_at: "2026-09-10T04:00:00Z",
  };
}

async function renderRecord(
  mode: "show" | "edit",
  changeLog: { enabled: boolean; retentionDays: number | null },
) {
  const entity = unpublishedEntity();
  const version = versionFor(entity, changeLog);
  vi.mocked(getEntity).mockResolvedValue({ entity });
  vi.mocked(listVersions).mockResolvedValue({
    items: [version],
    total: 1,
    limit: 200,
    offset: 0,
  });
  vi.mocked(getVersion).mockResolvedValue({ version });
  vi.mocked(patchEntity).mockResolvedValue({ entity });
  const { EntityRecord } = await import("@/features/entities/EntityRecord");
  render(
    createElement(
      MantineProvider,
      null,
      createElement(EntityRecord, { mode, entityId: entity.id }),
    ),
  );
  await screen.findByText("Material · material");
}

describe("entity change-log draft on the record form", () => {
  beforeEach(() => {
    stubDomApis();
    writePermission.can = true;
    vi.clearAllMocks();
  });

  afterEach(() => {
    cleanup();
  });

  it("shows the switch and the retention as text", async () => {
    await renderRecord("show", { enabled: true, retentionDays: 7 });
    expect(screen.getByText("Record changes")).toBeTruthy();
    expect(screen.getByText("Yes")).toBeTruthy();
    expect(screen.getByText("Retention (days)")).toBeTruthy();
    expect(screen.getByText("7")).toBeTruthy();
    expect(screen.queryByRole("switch")).toBeNull();
  });

  it("saves the draft switch and retention without publishing", async () => {
    await renderRecord("edit", { enabled: false, retentionDays: null });
    fireEvent.click(screen.getByRole("switch", { name: "Record changes" }));
    fireEvent.change(screen.getByLabelText("Retention (days)"), {
      target: { value: "14" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Save" }));
    await waitFor(() => {
      expect(patchEntity).toHaveBeenCalledWith(
        "ent_1",
        expect.objectContaining({
          change_log_enabled: true,
          change_log_retention_days: 14,
        }),
      );
    });
    expect(publishVersion).not.toHaveBeenCalled();
  });

  it("does not save when cancel is chosen", async () => {
    await renderRecord("edit", { enabled: true, retentionDays: 30 });
    fireEvent.click(screen.getByRole("switch", { name: "Record changes" }));
    fireEvent.click(screen.getByRole("link", { name: "Cancel" }));
    expect(patchEntity).not.toHaveBeenCalled();
    expect(publishVersion).not.toHaveBeenCalled();
  });

  it("shows the fields as text and does not save without definition-edit permission", async () => {
    writePermission.can = false;
    await renderRecord("edit", { enabled: true, retentionDays: 7 });
    expect(screen.queryByRole("switch")).toBeNull();
    expect(screen.getByText("Yes")).toBeTruthy();
    expect(screen.getByText("7")).toBeTruthy();
    expect(screen.getByText("Retention (days)")).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "Save" }));
    expect(patchEntity).not.toHaveBeenCalled();
    expect(publishVersion).not.toHaveBeenCalled();
  });

  it("shows never-expire as text when retention is empty", async () => {
    await renderRecord("show", { enabled: false, retentionDays: null });
    expect(screen.getByText("No")).toBeTruthy();
    expect(screen.getByText("Never expire")).toBeTruthy();
    expect(screen.queryByRole("switch")).toBeNull();
  });

  it("keeps the retention number when the draft switch is turned off", async () => {
    await renderRecord("edit", { enabled: true, retentionDays: 30 });
    fireEvent.click(screen.getByRole("switch", { name: "Record changes" }));
    fireEvent.click(screen.getByRole("button", { name: "Save" }));
    await waitFor(() => {
      expect(patchEntity).toHaveBeenCalledWith(
        "ent_1",
        expect.objectContaining({
          change_log_enabled: false,
          change_log_retention_days: 30,
        }),
      );
    });
    expect(publishVersion).not.toHaveBeenCalled();
  });

  it("sends the switch and retention when creating an entity", async () => {
    vi.mocked(createEntity).mockImplementation(() => new Promise(() => {}));
    const { EntityRecord } = await import("@/features/entities/EntityRecord");
    render(
      createElement(
        MantineProvider,
        null,
        createElement(EntityRecord, { mode: "create" }),
      ),
    );
    fireEvent.change(screen.getByRole("textbox", { name: /Table name/ }), {
      target: { value: "material" },
    });
    fireEvent.change(screen.getByRole("textbox", { name: /^Name/ }), {
      target: { value: "Material" },
    });
    fireEvent.change(screen.getByRole("textbox", { name: /Description/ }), {
      target: { value: "A material" },
    });
    fireEvent.click(screen.getByRole("switch", { name: "Record changes" }));
    fireEvent.change(screen.getByLabelText("Retention (days)"), {
      target: { value: "14" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Save" }));
    await waitFor(() => {
      expect(createEntity).toHaveBeenCalledWith(
        expect.objectContaining({
          table_name: "material",
          change_log_enabled: true,
          change_log_retention_days: 14,
        }),
      );
    });
    expect(publishVersion).not.toHaveBeenCalled();
  });
});
