/** @vitest-environment jsdom */

import { MantineProvider } from "@mantine/core";
import { notifications, notificationsStore } from "@mantine/notifications";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { createElement, type ReactNode } from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { createEntity, getEntity, getVersion, listVersions, patchEntity } from "@/features/entities/api";
import { getJob } from "@/features/jobs/api";
import type { BusinessEntity, EntityVersion } from "@/features/entities/types";
import { ApiError } from "@/lib/api";
import { ConsoleNotifications } from "@/providers/notification-provider";

const openNotice = vi.hoisted(() => vi.fn());

vi.mock("@refinedev/core", () => ({
  matchResourceFromRoute: () => ({ found: false }),
  useTranslate: () => (key: string) => key,
  useNotification: () => ({ open: openNotice }),
  useCan: () => ({ data: { can: true } }),
  usePermissions: () => ({ data: [] as string[] }),
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
  usePathname: () => "/console/entities/show/ent_1",
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

function resetNotifications() {
  const state = notificationsStore.getState();
  for (const item of [...state.notifications, ...state.queue]) {
    notifications.hide(item.id);
  }
  notifications.clean();
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

function versionFor(entity: BusinessEntity): EntityVersion {
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
    change_log_enabled: false,
    change_log_retention_days: null,
    created_at: "2026-09-10T04:00:00Z",
    updated_at: "2026-09-10T04:00:00Z",
  };
}

function shell(node: ReactNode) {
  return createElement(
    MantineProvider,
    { env: "test" },
    createElement(ConsoleNotifications),
    node,
  );
}

describe("EntityRecord feedback", () => {
  beforeEach(() => {
    stubDomApis();
    resetNotifications();
    openNotice.mockClear();
    const entity = unpublishedEntity();
    vi.mocked(listVersions).mockResolvedValue({
      items: [versionFor(entity)],
      total: 1,
      limit: 200,
      offset: 0,
    });
    vi.mocked(getVersion).mockResolvedValue({ version: versionFor(entity) });
  });

  afterEach(() => {
    cleanup();
    resetNotifications();
    vi.clearAllMocks();
  });

  it("keeps the header, shows unloaded, and retries the failed load from the notification", async () => {
    const entity = unpublishedEntity();
    vi.mocked(getEntity)
      .mockRejectedValueOnce(
        new ApiError(500, "NO_SUCH_CODE", "Raw English detail", "req-entity"),
      )
      .mockResolvedValue({ entity });

    const { EntityRecord } = await import("@/features/entities/EntityRecord");
    render(shell(createElement(EntityRecord, { mode: "show", entityId: "ent_1" })));

    expect(await screen.findByRole("button", { name: "status.unloaded" })).toBeTruthy();
    expect(screen.getByRole("heading", { name: "entities.title" })).toBeTruthy();
    expect(screen.getByText("entities.description")).toBeTruthy();
    expect(screen.queryByText("common.error.loadFailed")).toBeNull();
    expect(openNotice).not.toHaveBeenCalled();
    expect(await screen.findAllByRole("alert")).toHaveLength(1);
    expect(screen.getByText("problems.unknown").closest("details")).toBeNull();
    expect(screen.getByText("Raw English detail").closest("details")).toBeTruthy();
    fireEvent.click(screen.getByText("form.error.details"));
    expect(screen.getByText("Raw English detail").closest("details")).toBeTruthy();
    expect(screen.getByText("common.requestId: req-entity").closest("details")).toBeTruthy();

    fireEvent.click(screen.getByRole("button", { name: "common.retry" }));
    expect(await screen.findByText("Material · material")).toBeTruthy();
    expect(screen.queryByRole("button", { name: "status.unloaded" })).toBeNull();
    expect(getEntity).toHaveBeenCalledTimes(2);
    expect(getEntity).toHaveBeenCalledWith("ent_1");
  });

  it("reports a rejected create as one notification and no save summary", async () => {
    vi.mocked(createEntity).mockRejectedValue(
      new ApiError(500, "NO_SUCH_CODE", "Raw English detail", "req-create"),
    );
    const { EntityRecord } = await import("@/features/entities/EntityRecord");
    render(shell(createElement(EntityRecord, { mode: "create" })));

    fireEvent.change(screen.getByRole("textbox", { name: /entities.fields.tableName/ }), {
      target: { value: "material" },
    });
    fireEvent.change(screen.getByRole("textbox", { name: /entities.fields.name/ }), {
      target: { value: "Material" },
    });
    fireEvent.change(screen.getByRole("textbox", { name: /entities.fields.description/ }), {
      target: { value: "A material" },
    });
    fireEvent.click(screen.getByRole("button", { name: "entities.create.submit" }));

    expect(await screen.findAllByRole("alert")).toHaveLength(1);
    const form = document.getElementById("entity-record-form");
    expect(form?.querySelector("[role='alert']")).toBeNull();
    expect(screen.getByText("problems.unknown").closest("details")).toBeNull();
    fireEvent.click(screen.getByText("form.error.details"));
    expect(screen.getByText("Raw English detail").closest("details")).toBeTruthy();
    expect(screen.getByText("common.requestId: req-create").closest("details")).toBeTruthy();
    expect(form?.textContent).not.toContain("Raw English detail");
  });

  it("marks a mapped edit field and discloses only the unmapped detail", async () => {
    const entity = unpublishedEntity();
    vi.mocked(getEntity).mockResolvedValue({ entity });
    vi.mocked(patchEntity).mockRejectedValue(
      new ApiError(422, "REQUEST_INVALID", "Request validation failed", "req-edit", {}, [
        { field: "name", message: "Name is taken" },
        { field: "retired", message: "Unknown field" },
      ]),
    );
    const { EntityRecord } = await import("@/features/entities/EntityRecord");
    render(shell(createElement(EntityRecord, { mode: "edit", entityId: "ent_1" })));
    expect(await screen.findByRole("textbox", { name: /entities.fields.name/ })).toBeTruthy();

    fireEvent.click(screen.getByRole("button", { name: "entities.edit.submit" }));

    expect(await screen.findByText("Name is taken")).toBeTruthy();
    expect(await screen.findAllByRole("alert")).toHaveLength(1);
    const form = document.getElementById("entity-record-form");
    expect(form?.querySelector("[role='alert']")).toBeNull();
    fireEvent.click(screen.getByText("form.error.details"));
    const disclosure = screen.getByText("form.error.details").closest("details");
    expect(disclosure?.textContent).toContain("retired: Unknown field");
    expect(disclosure?.textContent).not.toContain("Name is taken");
    expect(form?.textContent).not.toContain("Unknown field");
  });

  it("marks a fully mapped create field and sends no notification", async () => {
    vi.mocked(createEntity).mockRejectedValue(
      new ApiError(422, "REQUEST_INVALID", "Request validation failed", "req-full", {}, [
        { field: "name", message: "Name is taken" },
      ]),
    );
    const { EntityRecord } = await import("@/features/entities/EntityRecord");
    render(shell(createElement(EntityRecord, { mode: "create" })));
    fireEvent.change(screen.getByRole("textbox", { name: /entities.fields.tableName/ }), {
      target: { value: "material" },
    });
    fireEvent.change(screen.getByRole("textbox", { name: /entities.fields.name/ }), {
      target: { value: "Material" },
    });
    fireEvent.change(screen.getByRole("textbox", { name: /entities.fields.description/ }), {
      target: { value: "A material" },
    });
    fireEvent.click(screen.getByRole("button", { name: "entities.create.submit" }));

    expect(await screen.findByText("Name is taken")).toBeTruthy();
    expect(screen.queryByRole("alert")).toBeNull();
    expect(document.getElementById("entity-record-form")?.querySelector("[role='alert']")).toBeNull();
  });

  it("stays silent when the watched publish job fails", async () => {
    const entity: BusinessEntity = {
      ...unpublishedEntity(),
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
    vi.mocked(getEntity).mockResolvedValue({ entity });
    vi.mocked(listVersions).mockResolvedValue({
      items: [versionFor(entity)],
      total: 1,
      limit: 200,
      offset: 0,
    });
    vi.mocked(getVersion).mockResolvedValue({ version: versionFor(entity) });
    vi.mocked(getJob).mockRejectedValue(
      new ApiError(500, "NO_SUCH_CODE", "job missing", "req-job"),
    );

    const { EntityRecord } = await import("@/features/entities/EntityRecord");
    render(shell(createElement(EntityRecord, { mode: "show", entityId: "ent_1" })));

    expect(await screen.findByText("Material · material")).toBeTruthy();
    await waitFor(() => {
      expect(getJob).toHaveBeenCalledWith("job_pub", expect.anything());
    });
    expect(screen.queryByRole("alert")).toBeNull();
    expect(screen.queryByText("liveStatus.stale")).toBeNull();
    expect(screen.queryByRole("button", { name: "status.unloaded" })).toBeNull();
    expect(openNotice).not.toHaveBeenCalled();
  });
});
