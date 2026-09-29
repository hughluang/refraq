/** @vitest-environment jsdom */

import { MantineProvider } from "@mantine/core";
import {
  cleanup,
  fireEvent,
  render,
  screen,
  waitFor,
  within,
} from "@testing-library/react";
import { createElement, type ReactNode } from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import {
  deprecateEntity,
  getEntity,
  getVersion,
  listVersions,
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
  "entities.publish": "Publish",
  "entities.publish.confirmTitle": "Publish this Business Entity?",
  "entities.publish.confirmBody":
    "Publish “{{name}}”. Creates this version's Entity Table and freezes the definition.",
  "entities.publish.queued": "Publish job queued",
  "entities.deprecate": "Deprecate",
  "entities.deprecate.confirmTitle": "Deprecate this Business Entity?",
  "entities.deprecate.confirmBody":
    "Deprecate “{{name}}”. Authoring stops. This cannot be undone.",
  "entities.deprecate.success": "Business Entity deprecated",
  "jobs.refresh": "Refresh",
  "actions.edit": "Edit",
  "actions.delete": "Delete",
  "common.cancel": "Cancel",
  "common.confirm": "Confirm",
  "common.leaveUnsaved": "Leave?",
  "entities.status.notServing": "Not in service",
  "entities.status.serving": "In service",
  "entities.tabs.overview": "Overview",
  "entities.tabs.attributes": "Attributes",
  "entities.tabs.versions": "Versions",
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
  useCan: () => ({ data: { can: true } }),
  usePermissions: () => ({ data: [] }),
  useBreadcrumb: () => ({ breadcrumbs: [] }),
  CanAccess: ({ children }: { children: ReactNode }) => children,
}));

vi.mock("next/link", () => ({
  default: ({ href, children }: { href: string; children: ReactNode }) =>
    createElement("a", { href }, children),
}));

vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: vi.fn(), replace: vi.fn() }),
  useSearchParams: () => new URLSearchParams(),
}));

vi.mock("@/features/entities/api", () => ({
  getEntity: vi.fn(),
  listVersions: vi.fn(),
  getVersion: vi.fn(),
  publishVersion: vi.fn(),
  deprecateEntity: vi.fn(),
  createEntity: vi.fn(),
  deleteEntity: vi.fn(),
  enqueueDropTable: vi.fn(),
  openVersion: vi.fn(),
  patchEntity: vi.fn(),
}));

vi.mock("@/features/entities/EntityOverviewTab", () => ({
  EntityOverviewTab: () => createElement("div", null, "overview"),
}));

vi.mock("@/features/entities/EntityIdentityFields", () => ({
  EntityIdentityFields: () => createElement("div", null, "identity"),
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
  };
}

function publishedEntity(): BusinessEntity {
  return {
    ...unpublishedEntity(),
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
  };
}

function versionFor(entity: BusinessEntity): EntityVersion {
  const current = entity.current_version!;
  return {
    id: current.id,
    entity_id: entity.id,
    version: current.version,
    publish_status: current.publish_status,
    attributes: [
      {
        name: "sku",
        type: "string",
        required: true,
        unique: true,
        indexed: false,
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

async function renderRecord(entity: BusinessEntity) {
  vi.mocked(getEntity).mockResolvedValue({ entity });
  vi.mocked(listVersions).mockResolvedValue({
    items: [versionFor(entity)],
    total: 1,
    limit: 200,
    offset: 0,
  });
  vi.mocked(getVersion).mockResolvedValue({ version: versionFor(entity) });

  const { EntityRecord } = await import("@/features/entities/EntityRecord");
  render(
    createElement(
      MantineProvider,
      null,
      createElement(EntityRecord, { mode: "show", entityId: entity.id }),
    ),
  );
  await waitFor(() => {
    expect(screen.getByRole("button", { name: /Publish|Deprecate/ })).not.toBeNull();
  });
}

describe("EntityRecord lifecycle confirms", () => {
  beforeEach(() => {
    stubDomApis();
    vi.clearAllMocks();
  });

  afterEach(() => {
    cleanup();
  });

  it("does not publish until the confirm modal is accepted", async () => {
    vi.mocked(publishVersion).mockResolvedValue({
      job: { id: "job_pub", status: "queued" },
    } as never);
    await renderRecord(unpublishedEntity());

    fireEvent.click(screen.getByRole("button", { name: "Publish" }));
    expect(publishVersion).not.toHaveBeenCalled();
    const publishDialog = await screen.findByRole("dialog");
    expect(publishDialog.textContent).toContain("Publish this Business Entity?");
    expect(publishDialog.textContent).toContain(
      "Creates this version's Entity Table and freezes the definition.",
    );

    fireEvent.click(within(publishDialog).getByRole("button", { name: "Cancel" }));
    await waitFor(() => {
      expect(screen.queryByRole("dialog")).toBeNull();
    });
    expect(publishVersion).not.toHaveBeenCalled();

    fireEvent.click(screen.getByRole("button", { name: "Publish" }));
    const confirmDialog = await screen.findByRole("dialog");
    fireEvent.click(within(confirmDialog).getByRole("button", { name: "Publish" }));
    await waitFor(() => {
      expect(publishVersion).toHaveBeenCalledWith("ent_1", "encv_1");
    });
  });

  it("does not deprecate until the confirm modal is accepted", async () => {
    vi.mocked(deprecateEntity).mockResolvedValue({
      entity: { ...publishedEntity(), deprecated_at: "2026-09-11T00:00:00Z" },
    });
    await renderRecord(publishedEntity());

    fireEvent.click(screen.getByRole("button", { name: "Deprecate" }));
    expect(deprecateEntity).not.toHaveBeenCalled();
    const deprecateDialog = await screen.findByRole("dialog");
    expect(deprecateDialog.textContent).toContain(
      "Deprecate this Business Entity?",
    );
    expect(deprecateDialog.textContent).toContain("Authoring stops.");

    fireEvent.click(within(deprecateDialog).getByRole("button", { name: "Cancel" }));
    await waitFor(() => {
      expect(screen.queryByRole("dialog")).toBeNull();
    });
    expect(deprecateEntity).not.toHaveBeenCalled();

    fireEvent.click(screen.getByRole("button", { name: "Deprecate" }));
    const confirmDialog = await screen.findByRole("dialog");
    fireEvent.click(
      within(confirmDialog).getByRole("button", { name: "Deprecate" }),
    );
    await waitFor(() => {
      expect(deprecateEntity).toHaveBeenCalledWith("ent_1");
    });
  });
});
