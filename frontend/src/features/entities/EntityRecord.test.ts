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
import { getJob } from "@/features/jobs/api";
import type { BusinessEntity, EntityVersion } from "@/features/entities/types";

const permissions = vi.hoisted(() => ({ data: [] as string[] }));

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
  "entities.publish.confirmBodySuccessor":
    "Publish “{{name}}”. Creates this version's empty Entity Table and freezes the definition. After publish, the stem view and the Entity Data API read that new table. Rows on the previous version's table stay there and are not migrated.",
  "entities.publish.queued": "Publish job queued",
  "entities.deprecate": "Deprecate",
  "entities.deprecate.confirmTitle": "Deprecate this Business Entity?",
  "entities.deprecate.confirmBody":
    "Deprecate “{{name}}”. Authoring stops. This cannot be undone.",
  "entities.deprecate.consequence": "Authoring stops.",
  "feedback.confirm.body": "{{record}}: {{consequence}} This cannot be undone.",
  "feedback.success.title": "{{outcome}} — {{record}}",
  "problems.unknown": "Something went wrong.",
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
  "entities.tabs.data": "Data",
  "entities.tabs.changeLog": "Change log",
  "entities.fields.updatedAt": "Updated",
  "entities.fields.publishJob": "Publish job",
  "jobs.kind.entity_reconcile": "Entity publish",
  "status.job.running": "Running",
  "status.job.succeeded": "Succeeded",
  "status.job.failed": "Failed",
  "status.job.cancelled": "Cancelled",
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
  usePermissions: () => ({ data: permissions.data }),
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

vi.mock("@/features/jobs/api", () => ({
  getJob: vi.fn(),
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

function publishingEntity(): BusinessEntity {
  return {
    ...unpublishedEntity(),
    change_log_recording: false,
    current_version: {
      id: "encv_1",
      version: 1,
      publish_status: "publishing",
      table_name: null,
      alignment: {
        table_present: false,
        latest_job_id: "job_pub",
        latest_job_status: "running",
      },
    },
  };
}

function servedAfterPublish(): BusinessEntity {
  return {
    ...publishedEntity(),
    change_log_recording: true,
    current_version: {
      id: "encv_1",
      version: 1,
      publish_status: "published",
      table_name: "material",
      alignment: {
        table_present: true,
        latest_job_id: "job_pub",
        latest_job_status: "succeeded",
      },
    },
  };
}

function successorEntity(): BusinessEntity {
  return {
    ...unpublishedEntity(),
    ever_published: true,
    current_version: {
      id: "encv_2",
      version: 2,
      publish_status: "unpublished",
      table_name: null,
      alignment: {
        table_present: false,
        latest_job_id: null,
        latest_job_status: null,
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
        business_key: false,
        description: null,
        config: { max_length: 64 },
      },
    ],
    attribute_count: 1,
    table_name: current.table_name,
    alignment: current.alignment,
    change_log_enabled: false,
    change_log_retention_days: null,
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
  await screen.findByText("Material · material");
}

describe("EntityRecord lifecycle confirms", () => {
  beforeEach(() => {
    stubDomApis();
    permissions.data = [];
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
    expect(publishDialog.textContent).not.toContain("are not migrated");

    fireEvent.click(within(publishDialog).getByRole("button", { name: "Cancel" }));
    await waitFor(() => {
      expect(screen.queryByRole("dialog")).toBeNull();
    });
    expect(publishVersion).not.toHaveBeenCalled();

    fireEvent.click(screen.getByRole("button", { name: "Publish" }));
    const confirmDialog = await screen.findByRole("dialog");
    await waitFor(() => {
      expect(
        (within(confirmDialog).getByRole("button", { name: "Publish" }) as HTMLButtonElement)
          .disabled,
      ).toBe(false);
    });
    fireEvent.click(within(confirmDialog).getByRole("button", { name: "Publish" }));
    await waitFor(() => {
      expect(publishVersion).toHaveBeenCalledWith("ent_1", "encv_1");
    });
  });

  it("follows a publish already running when the record opens", async () => {
    permissions.data = ["entity:data_read"];
    let snapshot = publishingEntity();
    let resolveJob: (status: string) => void = () => {};
    vi.mocked(getEntity).mockImplementation(async () => ({ entity: snapshot }));
    vi.mocked(listVersions).mockImplementation(async () => ({
      items: [versionFor(snapshot)],
      total: 1,
      limit: 200,
      offset: 0,
    }));
    vi.mocked(getVersion).mockImplementation(async () => ({
      version: versionFor(snapshot),
    }));
    vi.mocked(getJob).mockImplementation(
      () =>
        new Promise((resolve) => {
          resolveJob = (status) =>
            resolve({
              job: { id: "job_pub", status },
            } as Awaited<ReturnType<typeof getJob>>);
        }),
    );

    const { EntityRecord } = await import("@/features/entities/EntityRecord");
    render(
      createElement(
        MantineProvider,
        null,
        createElement(EntityRecord, { mode: "show", entityId: "ent_1" }),
      ),
    );

    expect(await screen.findByText("Not in service")).toBeTruthy();
    expect(screen.getByText("Running")).toBeTruthy();
    expect(screen.queryByRole("tab", { name: "Change log" })).toBeNull();

    snapshot = servedAfterPublish();
    resolveJob("succeeded");

    expect(await screen.findByText("In service")).toBeTruthy();
    expect(screen.getByText("Succeeded")).toBeTruthy();
    expect(screen.getByRole("tab", { name: "Change log" })).toBeTruthy();
    expect(screen.queryByText("Running")).toBeNull();
    expect(getJob).toHaveBeenCalledWith("job_pub", expect.anything());
  });

  it.each(["failed", "cancelled"] as const)(
    "reloads the record when the publish job %s",
    async (status) => {
      const snapshot = publishingEntity();
      vi.mocked(getEntity).mockResolvedValue({ entity: snapshot });
      vi.mocked(listVersions).mockResolvedValue({
        items: [versionFor(snapshot)],
        total: 1,
        limit: 200,
        offset: 0,
      });
      vi.mocked(getVersion).mockResolvedValue({ version: versionFor(snapshot) });
      vi.mocked(getJob).mockResolvedValue({
        job: { id: "job_pub", status },
      } as Awaited<ReturnType<typeof getJob>>);

      const { EntityRecord } = await import("@/features/entities/EntityRecord");
      render(
        createElement(
          MantineProvider,
          null,
          createElement(EntityRecord, { mode: "show", entityId: "ent_1" }),
        ),
      );
      await screen.findByText("Material · material");
      await waitFor(() => {
        expect(vi.mocked(getEntity).mock.calls.length).toBeGreaterThanOrEqual(2);
      });
      expect(getJob).toHaveBeenCalledWith("job_pub", expect.anything());
    },
  );

  it("follows the version job after a publish started on the open record", async () => {
    permissions.data = ["entity:data_read"];
    await renderRecord(unpublishedEntity());
    let snapshot = publishingEntity();
    vi.mocked(getEntity).mockImplementation(async () => ({ entity: snapshot }));
    vi.mocked(listVersions).mockImplementation(async () => ({
      items: [versionFor(snapshot)],
      total: 1,
      limit: 200,
      offset: 0,
    }));
    vi.mocked(getVersion).mockImplementation(async () => ({
      version: versionFor(snapshot),
    }));
    vi.mocked(publishVersion).mockResolvedValue({
      job: { id: "job_pub", status: "queued" },
    } as never);
    vi.mocked(getJob).mockImplementation(async () => {
      snapshot = servedAfterPublish();
      return {
        job: { id: "job_pub", status: "succeeded" },
      } as Awaited<ReturnType<typeof getJob>>;
    });
    fireEvent.click(screen.getByRole("button", { name: "Publish" }));
    const confirmDialog = await screen.findByRole("dialog");
    await waitFor(() => {
      expect(
        (
          within(confirmDialog).getByRole("button", {
            name: "Publish",
          }) as HTMLButtonElement
        ).disabled,
      ).toBe(false);
    });
    fireEvent.click(within(confirmDialog).getByRole("button", { name: "Publish" }));

    expect(await screen.findByText("In service")).toBeTruthy();
    expect(screen.getByRole("tab", { name: "Change log" })).toBeTruthy();
    expect(getJob).toHaveBeenCalledWith("job_pub", expect.anything());
  });

  it("keeps a newer entity read when an older one finishes later", async () => {
    let snapshot = publishingEntity();
    let entityReads = 0;
    let releaseStale: () => void = () => {};
    vi.mocked(getEntity).mockImplementation(() => {
      entityReads += 1;
      const entity = snapshot;
      if (entityReads === 2) {
        return new Promise((resolve) => {
          releaseStale = () => resolve({ entity });
        });
      }
      return Promise.resolve({ entity });
    });
    vi.mocked(listVersions).mockImplementation(async () => ({
      items: [versionFor(snapshot)],
      total: 1,
      limit: 200,
      offset: 0,
    }));
    vi.mocked(getVersion).mockImplementation(async () => ({
      version: versionFor(snapshot),
    }));
    let resolveJob: (status: string) => void = () => {};
    vi.mocked(getJob).mockImplementation(
      () =>
        new Promise((resolve) => {
          resolveJob = (status) =>
            resolve({
              job: { id: "job_pub", status },
            } as Awaited<ReturnType<typeof getJob>>);
        }),
    );

    const { EntityRecord } = await import("@/features/entities/EntityRecord");
    render(
      createElement(
        MantineProvider,
        null,
        createElement(EntityRecord, { mode: "show", entityId: "ent_1" }),
      ),
    );
    expect(await screen.findByText("Running")).toBeTruthy();

    fireEvent.click(screen.getByRole("button", { name: "Refresh" }));
    snapshot = servedAfterPublish();
    resolveJob("succeeded");
    expect(await screen.findByText("In service")).toBeTruthy();

    releaseStale();
    await waitFor(() => {
      expect(vi.mocked(getEntity).mock.calls.length).toBeGreaterThanOrEqual(3);
    });
    expect(screen.getByText("In service")).toBeTruthy();
    expect(screen.queryByText("Running")).toBeNull();
    expect(screen.getByText("Succeeded")).toBeTruthy();
  });

  it("tells a successor publish that the product entry reads the new empty table", async () => {
    await renderRecord(successorEntity());

    fireEvent.click(screen.getByRole("button", { name: "Publish" }));
    const publishDialog = await screen.findByRole("dialog");
    expect(publishDialog.textContent).toContain("stem view");
    expect(publishDialog.textContent).toContain("Entity Data API");
    expect(publishDialog.textContent).toContain("are not migrated");
    expect(publishDialog.textContent).not.toContain(
      "Creates this version's Entity Table and freezes the definition.",
    );
    expect(publishVersion).not.toHaveBeenCalled();
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
