/** @vitest-environment jsdom */

import { MantineProvider } from "@mantine/core";
import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { createElement, type ReactNode } from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import {
  getEntity,
  getEntityChangeLogEntry,
  getVersion,
  listEntityChangeLog,
  listVersions,
} from "@/features/entities/api";
import { ChangeLogDraftProvider } from "@/features/entities/changeLogDraft";
import { ApiError } from "@/lib/api";
import type {
  BusinessEntity,
  ChangeLogEntrySummary,
  ChangeLogSide,
  EntityVersion,
} from "@/features/entities/types";

const permissions = vi.hoisted(() => ({ data: [] as string[] }));
const writePermission = vi.hoisted(() => ({ can: true }));

const LABELS: Record<string, string> = {
  "entities.title": "Business Entities",
  "entities.description": "Definitions",
  "entities.edit.title": "Edit entity",
  "entities.create.title": "Create Business Entity",
  "entities.backToList": "Back",
  "entities.actions.navigation": "Navigation",
  "entities.actions.lifecycle": "Lifecycle",
  "entities.actions.standard": "Standard",
  "entities.tabs.overview": "Overview",
  "entities.tabs.attributes": "Attributes",
  "entities.tabs.versions": "Versions",
  "entities.tabs.data": "Data",
  "entities.tabs.changeLog": "Change log",
  "entities.status.notServing": "Not in service",
  "entities.status.serving": "In service",
  "entities.fields.changeLogEnabled": "Record changes",
  "entities.fields.changeLogRetentionDays": "Retention (days)",
  "entities.fields.changeLogRetentionNever": "Never expire",
  "entities.fields.tableName": "Table name",
  "entities.fields.name": "Name",
  "entities.fields.description": "Description",
  "entities.changeLog.sequence": "Sequence",
  "entities.changeLog.occurredAt": "Time",
  "entities.changeLog.operation": "Operation",
  "entities.changeLog.rowIdentity": "Row",
  "entities.changeLog.version": "Version",
  "entities.changeLog.source": "Source",
  "entities.changeLog.subject": "Subject",
  "entities.changeLog.older": "Older",
  "entities.changeLog.newest": "Newest",
  "entities.changeLog.empty": "No changes recorded.",
  "entities.changeLog.loading": "Loading changes",
  "entities.changeLog.failed": "Could not load changes",
  "entities.changeLog.before": "Before",
  "entities.changeLog.after": "After",
  "entities.changeLog.unavailable": "Unavailable",
  "entities.changeLog.withheld": "Withheld",
  "problems.REQUEST_INVALID": "The request is not valid. Check the fields and try again.",
  "entities.changeLog.filter.any": "Any",
  "entities.changeLog.filter.operation": "Operation",
  "entities.changeLog.filter.source": "Source",
  "entities.changeLog.filter.subject": "Subject",
  "entities.changeLog.filter.subjectHint":
    "Matches the stored id. A display name does not match.",
  "entities.changeLog.filter.instantHint": "Interpreted in {{zone}}.",
  "entities.changeLog.filter.rowIdentity": "Business key",
  "entities.changeLog.filter.versionId": "Version id",
  "entities.changeLog.filter.rowId": "Row id",
  "entities.changeLog.filter.from": "From",
  "entities.changeLog.filter.to": "To",
  "entities.changeLog.operation.insert": "Insert",
  "entities.changeLog.operation.update": "Update",
  "entities.changeLog.operation.delete": "Delete",
  "entities.changeLog.source.user": "User",
  "entities.changeLog.source.channelRun": "Channel run",
  "entities.changeLog.source.unattributed": "Unattributed",
  "form.value.yes": "Yes",
  "form.value.no": "No",
  "jobs.refresh": "Refresh",
  "actions.edit": "Edit",
  "common.cancel": "Cancel",
  "entities.edit.submit": "Save",
  "entities.create.submit": "Save",
};

vi.mock("@refinedev/core", () => ({
  matchResourceFromRoute: () => ({ found: false }),
  useTranslate: () => (key: string, values?: Record<string, unknown>) => {
    const template = LABELS[key] ?? key;
    if (!values) return template;
    return template.replace(/\{\{(\w+)\}\}/g, (_, name: string) =>
      String(values[name] ?? ""),
    );
  },
  useNotification: () => ({ open: vi.fn() }),
  useCan: () => ({ data: { can: writePermission.can } }),
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
  listEntityChangeLog: vi.fn(),
  getEntityChangeLogEntry: vi.fn(),
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
  useSessionStore: (
    selector?: (state: {
      user: { display_timezone: string; locale: string };
    }) => unknown,
  ) => {
    const state = { user: { display_timezone: "UTC", locale: "en-US" } };
    return selector ? selector(state) : state;
  },
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
    ever_published: true,
    change_log_recording: true,
    current_version: {
      id: "encv_1",
      version: 1,
      publish_status: "published",
      table_name: "material__v1__abcdef0123456789",
      alignment: {
        table_present: true,
        latest_job_id: "job_1",
        latest_job_status: "succeeded",
      },
    },
    created_at: "2026-09-10T04:00:00Z",
    updated_at: "2026-09-10T04:00:00Z",
    tags: [],
    tag_revision: 1,
    ...overrides,
  };
}

function versionFor(
  record: BusinessEntity,
  changeLogEnabled = false,
): EntityVersion {
  const current = record.current_version!;
  return {
    id: current.id,
    entity_id: record.id,
    version: current.version,
    publish_status: current.publish_status,
    attributes: [],
    attribute_count: 0,
    table_name: current.table_name,
    alignment: current.alignment,
    change_log_enabled: changeLogEnabled,
    change_log_retention_days: null,
    created_at: "2026-09-10T04:00:00Z",
    updated_at: "2026-09-10T04:00:00Z",
  };
}

function side(state: ChangeLogSide["state"], values?: Record<string, unknown>): ChangeLogSide {
  return values === undefined ? { state } : { state, values };
}

function entry(overrides: Partial<ChangeLogEntrySummary> = {}): ChangeLogEntrySummary {
  return {
    sequence: 4,
    occurred_at: "2026-10-02T00:00:00Z",
    operation: "insert",
    version_id: "ver_logical",
    version_number: 3,
    source: "user",
    subject: "user_ada",
    subject_label: "Ada",
    before: side("absent"),
    after: side("visible", { row_id: 7, sku: "LEFT" }),
    ...overrides,
  };
}

async function renderRecord(
  record: BusinessEntity,
  mode: "show" | "edit" | "create" = "show",
  changeLogEnabled = false,
) {
  vi.mocked(getEntity).mockResolvedValue({ entity: record });
  vi.mocked(listVersions).mockResolvedValue({
    items: mode === "create" ? [] : [versionFor(record, changeLogEnabled)],
    total: mode === "create" ? 0 : 1,
    limit: 200,
    offset: 0,
  });
  vi.mocked(getVersion).mockResolvedValue({
    version: versionFor(record, changeLogEnabled),
  });
  const { EntityRecord } = await import("@/features/entities/EntityRecord");
  const page = (next: BusinessEntity, nextMode: typeof mode = mode) =>
    nextMode === "create"
      ? createElement(EntityRecord, { mode: "create" })
      : createElement(EntityRecord, { mode: nextMode, entityId: next.id });
  const tree = (next: BusinessEntity, nextMode: typeof mode = mode) =>
    createElement(
      MantineProvider,
      null,
      createElement(ChangeLogDraftProvider, null, page(next, nextMode)),
    );
  const view = render(tree(record));
  if (mode !== "create") {
    await screen.findByText("Material · material");
  }
  return { ...view, tree };
}

describe("change log tab", () => {
  beforeEach(() => {
    stubDomApis();
    permissions.data = [];
    writePermission.can = true;
    vi.clearAllMocks();
    vi.mocked(listEntityChangeLog).mockResolvedValue({
      items: [],
      limit: 50,
      next_cursor: null,
    });
  });

  afterEach(() => {
    cleanup();
  });

  it("is absent on create", async () => {
    await renderRecord(entity(), "create");
    expect(screen.queryByRole("tab", { name: "Change log" })).toBeNull();
  });

  it("is absent unless recording is on and the operator can read data", async () => {
    permissions.data = ["entity:data_read"];
    await renderRecord(entity({ change_log_recording: false }));
    expect(screen.queryByRole("tab", { name: "Change log" })).toBeNull();
    cleanup();

    permissions.data = [];
    await renderRecord(entity({ change_log_recording: true }));
    expect(screen.queryByRole("tab", { name: "Change log" })).toBeNull();
  });

  it("stays on a published entity and on a draft that turns recording off", async () => {
    permissions.data = ["entity:data_read"];
    await renderRecord(entity());
    expect(screen.getByRole("tab", { name: "Change log" })).toBeTruthy();
    cleanup();

    const draft = entity({
      change_log_recording: true,
      effective_change_log: { enabled: true, retention_days: null },
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
    });
    await renderRecord(draft, "edit", false);
    expect(screen.getByRole("tab", { name: "Change log" })).toBeTruthy();
    expect(screen.getByText("Record changes")).toBeTruthy();
  });

  it("lets an editor without data read keep the overview switch", async () => {
    permissions.data = ["entity:read", "entity:write"];
    const draft = entity({
      change_log_recording: true,
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
    });
    await renderRecord(draft, "edit", true);
    expect(screen.queryByRole("tab", { name: "Change log" })).toBeNull();
    expect(screen.getByText("Record changes")).toBeTruthy();
  });

  it("lists the newest page and asks for the continuation cursor", async () => {
    permissions.data = ["entity:data_read"];
    const newer = entry({
      sequence: 60,
      before: side("unavailable", { row_id: 99, sku: "HIDDEN" }),
      after: side("visible", { row_id: 1, sku: "NEW" }),
    });
    const older = entry({
      sequence: 11,
      after: side("visible", { row_id: 2, sku: "OLD" }),
    });
    vi.mocked(listEntityChangeLog).mockResolvedValue({
      items: [newer, older],
      limit: 50,
      next_cursor: "cursor-older",
    });
    await renderRecord(entity());
    fireEvent.click(screen.getByRole("tab", { name: "Change log" }));
    const newest = await screen.findByRole("button", { name: "60" });
    const row = newest.closest("tr");
    expect(row).toBeTruthy();
    expect(within(row as HTMLElement).getByText("1")).toBeTruthy();
    expect(within(row as HTMLElement).queryByText("99")).toBeNull();
    expect(within(row as HTMLElement).queryByText("HIDDEN")).toBeNull();
    expect(screen.queryByText("Physical table")).toBeNull();
    expect(within(row as HTMLElement).getByText("ver_logical")).toBeTruthy();
    expect(within(row as HTMLElement).getByText("3")).toBeTruthy();
    expect(within(row as HTMLElement).getByText("Insert")).toBeTruthy();
    expect(within(row as HTMLElement).getByText("Ada")).toBeTruthy();
    expect(within(row as HTMLElement).getByText("user_ada")).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "Older" }));
    await waitFor(() => {
      const last = vi.mocked(listEntityChangeLog).mock.calls.at(-1);
      expect(last?.[1]?.cursor).toBe("cursor-older");
    });
    fireEvent.click(screen.getByRole("button", { name: "Newest" }));
    await waitFor(() => {
      const last = vi.mocked(listEntityChangeLog).mock.calls.at(-1);
      expect(last?.[1]?.cursor).toBeUndefined();
      expect(last?.[1]?.operation).toBeUndefined();
    });
    expect(screen.queryByRole("button", { name: "Newest" })).toBeNull();
  });

  it("sends combined filters and shows one entry's physical images", async () => {
    permissions.data = ["entity:data_read"];
    const userRow = entry({ sequence: 8, subject_label: "Ada", subject: "user_ada" });
    const missing = entry({
      sequence: 7,
      subject: "usr_missing",
      subject_label: "usr_missing",
      after: side("visible", { row_id: 3, sku: "GONE" }),
    });
    const run = entry({
      sequence: 6,
      source: "channel_run",
      subject: "run_9",
      subject_label: "run_9",
      operation: "update",
    });
    const plain = entry({
      sequence: 5,
      source: null,
      subject: null,
      subject_label: null,
      operation: "delete",
    });
    vi.mocked(listEntityChangeLog).mockResolvedValue({
      items: [userRow, missing, run, plain],
      limit: 50,
      next_cursor: null,
    });
    vi.mocked(getEntityChangeLogEntry).mockResolvedValue({
      ...userRow,
      before: side("absent"),
      after: side("visible", { row_id: 7, sku: "LEFT", secret: "hidden" }),
    });
    await renderRecord(entity());
    fireEvent.click(screen.getByRole("tab", { name: "Change log" }));
    await screen.findByRole("button", { name: "8" });
    expect(screen.getByText("user_ada")).toBeTruthy();
    expect(screen.getByText("usr_missing")).toBeTruthy();
    expect(screen.getByText("run_9")).toBeTruthy();
    expect(screen.getAllByText("usr_missing")).toHaveLength(1);
    expect(screen.getAllByText("run_9")).toHaveLength(1);
    expect(document.querySelector('a[href*="run_9"]')).toBeNull();
    const plainRow = screen.getByRole("button", { name: "5" }).closest("tr");
    expect(plainRow).toBeTruthy();
    const cells = within(plainRow as HTMLElement).getAllByRole("cell");
    expect(cells[6]?.textContent).toBe("");

    fireEvent.change(screen.getByLabelText("Operation"), {
      target: { value: "update" },
    });
    fireEvent.change(screen.getByLabelText("Source"), {
      target: { value: "user" },
    });
    fireEvent.change(screen.getByLabelText("Subject"), {
      target: { value: "usr_a" },
    });
    fireEvent.change(screen.getByLabelText("Business key"), {
      target: { value: "LEFT" },
    });
    fireEvent.change(screen.getByLabelText("Version id"), {
      target: { value: "ver_1" },
    });
    fireEvent.change(screen.getByLabelText("Row id"), {
      target: { value: "7" },
    });
    expect(
      screen.getByText("Matches the stored id. A display name does not match."),
    ).toBeTruthy();
    expect(screen.getAllByText("Interpreted in UTC.").length).toBe(2);
    fireEvent.change(screen.getByLabelText("From"), {
      target: { value: "2026-10-02T00:00:00" },
    });
    fireEvent.change(screen.getByLabelText("To"), {
      target: { value: "2026-10-03T00:00:00" },
    });
    await waitFor(() => {
      const last = vi.mocked(listEntityChangeLog).mock.calls.at(-1);
      expect(last?.[1]).toMatchObject({
        operation: "update",
        source: "user",
        subject: "usr_a",
        row_identity: "LEFT",
        version_id: "ver_1",
        row_id: "7",
        occurred_from: "2026-10-02T00:00:00Z",
        occurred_to: "2026-10-03T00:00:00Z",
      });
      expect(last?.[1]?.cursor).toBeUndefined();
    });

    fireEvent.click(screen.getByRole("button", { name: "8" }));
    const after = await screen.findByRole("region", { name: "After" });
    expect(after.textContent).toContain("secret");
    expect(after.textContent).toContain("hidden");
    expect(after.textContent).toContain("sku");
    expect(screen.queryByRole("region", { name: "Before" })).toBeNull();
  });

  it("shows a json value as JSON text", async () => {
    permissions.data = ["entity:data_read"];
    const row = entry({ sequence: 9 });
    vi.mocked(listEntityChangeLog).mockResolvedValue({
      items: [row],
      limit: 50,
      next_cursor: null,
    });
    vi.mocked(getEntityChangeLogEntry).mockResolvedValue({
      ...row,
      before: side("unavailable", { sku: "LEAK" }),
      after: side("visible", {
        row_id: 7,
        sku: "LEFT",
        qty: 3,
        flag: false,
        note: null,
        secret: "clear-secret",
        __withheld: ["secret"],
        payload: { code: "A" },
        tags: ["x", 1],
      }),
    });
    await renderRecord(entity());
    fireEvent.click(screen.getByRole("tab", { name: "Change log" }));
    fireEvent.click(await screen.findByRole("button", { name: "9" }));
    const after = await screen.findByRole("region", { name: "After" });
    expect(after.textContent).toContain('payload: {"code":"A"}');
    expect(after.textContent).toContain('tags: ["x",1]');
    expect(after.textContent).toContain("sku: LEFT");
    expect(after.textContent).toContain("qty: 3");
    expect(after.textContent).toContain("flag: false");
    expect(after.textContent).toContain("note: ");
    expect(after.textContent).toContain("secret: Withheld");
    expect(after.textContent).not.toContain("clear-secret");
    expect(after.textContent).not.toContain("__withheld");
    expect(after.textContent).not.toContain("[object Object]");
    expect(after.textContent).not.toContain("note: null");
    const before = screen.getByRole("region", { name: "Before" });
    expect(before.textContent).toContain("Unavailable");
    expect(before.textContent).not.toContain("LEAK");
  });

  it("keeps the tab when the log is empty", async () => {
    permissions.data = ["entity:data_read"];
    await renderRecord(entity());
    fireEvent.click(screen.getByRole("tab", { name: "Change log" }));
    expect(await screen.findByText("No changes recorded.")).toBeTruthy();
    expect(screen.getByRole("tab", { name: "Change log" })).toBeTruthy();
  });

  it("keeps older on an empty continuation and does not call that the end", async () => {
    permissions.data = ["entity:data_read"];
    vi.mocked(listEntityChangeLog).mockResolvedValue({
      items: [],
      limit: 50,
      next_cursor: "cursor-more",
    });
    await renderRecord(entity());
    fireEvent.click(screen.getByRole("tab", { name: "Change log" }));
    expect(await screen.findByRole("button", { name: "Older" })).toBeTruthy();
    expect(screen.queryByText("No changes recorded.")).toBeNull();
  });

  it("does not call a later exhausted page empty history", async () => {
    permissions.data = ["entity:data_read"];
    vi.mocked(listEntityChangeLog).mockImplementation(async (_entityId, query) => {
      if (query?.cursor === "cursor-last") {
        return { items: [], limit: 50, next_cursor: null };
      }
      return {
        items: [entry({ sequence: 8 })],
        limit: 50,
        next_cursor: "cursor-last",
      };
    });
    await renderRecord(entity());
    fireEvent.click(screen.getByRole("tab", { name: "Change log" }));
    fireEvent.click(await screen.findByRole("button", { name: "Older" }));
    await waitFor(() => {
      const last = vi.mocked(listEntityChangeLog).mock.calls.at(-1);
      expect(last?.[1]?.cursor).toBe("cursor-last");
    });
    expect(screen.queryByText("No changes recorded.")).toBeNull();
    expect(screen.getByRole("button", { name: "Newest" })).toBeTruthy();
    expect(screen.queryByRole("button", { name: "Older" })).toBeNull();
  });

  it("shows the problem for a rejected cursor and does not retry", async () => {
    permissions.data = ["entity:data_read"];
    vi.mocked(listEntityChangeLog).mockImplementation(async (_entityId, query) => {
      if (query?.cursor === "cursor-bad") {
        throw new ApiError(422, "REQUEST_INVALID", "Request validation failed");
      }
      return {
        items: [entry({ sequence: 8 })],
        limit: 50,
        next_cursor: "cursor-bad",
      };
    });
    await renderRecord(entity());
    fireEvent.click(screen.getByRole("tab", { name: "Change log" }));
    fireEvent.click(await screen.findByRole("button", { name: "Older" }));
    expect(
      await screen.findByText("The request is not valid. Check the fields and try again."),
    ).toBeTruthy();
    expect(screen.queryByText("No changes recorded.")).toBeNull();
    await waitFor(() => {
      const calls = vi.mocked(listEntityChangeLog).mock.calls;
      expect(calls.at(-1)?.[1]?.cursor).toBe("cursor-bad");
    });
    const seen = vi.mocked(listEntityChangeLog).mock.calls.length;
    await new Promise((resolve) => setTimeout(resolve, 30));
    expect(vi.mocked(listEntityChangeLog)).toHaveBeenCalledTimes(seen);
  });

  it("reads the first page when the same tab opens another entity", async () => {
    permissions.data = ["entity:data_read"];
    const cursor = "cursor-from-ent_1";
    vi.mocked(listEntityChangeLog).mockImplementation(async (id, query) => {
      if (id === "ent_2" && query?.cursor) {
        throw new ApiError(422, "REQUEST_INVALID", "Request validation failed");
      }
      if (query?.cursor) {
        return { items: [entry({ sequence: 1 })], limit: 50, next_cursor: null };
      }
      return { items: [entry({ sequence: 8 })], limit: 50, next_cursor: cursor };
    });
    const view = await renderRecord(entity({ id: "ent_1" }));
    fireEvent.click(screen.getByRole("tab", { name: "Change log" }));
    fireEvent.change(screen.getByLabelText("Business key"), {
      target: { value: "LEFT" },
    });
    fireEvent.change(screen.getByLabelText("Version id"), {
      target: { value: "ver_kept" },
    });
    fireEvent.change(screen.getByLabelText("Row id"), {
      target: { value: "4" },
    });
    fireEvent.click(await screen.findByRole("button", { name: "Older" }));
    await waitFor(() => {
      const last = vi.mocked(listEntityChangeLog).mock.calls.at(-1);
      expect(last?.[0]).toBe("ent_1");
      expect(last?.[1]?.cursor).toBe(cursor);
    });
    const next = entity({ id: "ent_2" });
    vi.mocked(getEntity).mockResolvedValue({ entity: next });
    vi.mocked(listVersions).mockResolvedValue({
      items: [versionFor(next)],
      total: 1,
      limit: 200,
      offset: 0,
    });
    vi.mocked(getVersion).mockResolvedValue({ version: versionFor(next) });
    view.rerender(view.tree(next));
    await waitFor(() => {
      const switched = vi
        .mocked(listEntityChangeLog)
        .mock.calls.filter((call) => call[0] === "ent_2");
      expect(switched.length).toBeGreaterThan(0);
      expect(switched.every((call) => call[1]?.cursor == null)).toBe(true);
      expect(switched.at(-1)?.[1]).toMatchObject({
        row_identity: "LEFT",
        version_id: "ver_kept",
        row_id: "4",
      });
    });
    expect((screen.getByLabelText("Business key") as HTMLInputElement).value).toBe(
      "LEFT",
    );
    expect((screen.getByLabelText("Version id") as HTMLInputElement).value).toBe(
      "ver_kept",
    );
    expect((screen.getByLabelText("Row id") as HTMLInputElement).value).toBe("4");
    expect(
      screen.queryByText("The request is not valid. Check the fields and try again."),
    ).toBeNull();
  });

  it("keeps the filter draft after the page unmounts and drops the continuation", async () => {
    permissions.data = ["entity:data_read"];
    const cursor = "cursor-from-ent_1";
    vi.mocked(listEntityChangeLog).mockImplementation(async (id, query) => {
      if (query?.cursor) {
        return { items: [entry({ sequence: 1 })], limit: 50, next_cursor: null };
      }
      return { items: [entry({ sequence: 8 })], limit: 50, next_cursor: cursor };
    });
    const view = await renderRecord(entity({ id: "ent_1" }));
    fireEvent.click(screen.getByRole("tab", { name: "Change log" }));
    fireEvent.change(screen.getByLabelText("Business key"), {
      target: { value: "LEFT" },
    });
    fireEvent.change(screen.getByLabelText("Version id"), {
      target: { value: "ver_kept" },
    });
    fireEvent.change(screen.getByLabelText("Row id"), {
      target: { value: "4" },
    });
    fireEvent.click(await screen.findByRole("button", { name: "Older" }));
    await waitFor(() => {
      const last = vi.mocked(listEntityChangeLog).mock.calls.at(-1);
      expect(last?.[0]).toBe("ent_1");
      expect(last?.[1]?.cursor).toBe(cursor);
    });
    view.rerender(
      createElement(MantineProvider, null, createElement(ChangeLogDraftProvider, null, null)),
    );
    const next = entity({ id: "ent_2" });
    vi.mocked(getEntity).mockResolvedValue({ entity: next });
    vi.mocked(listVersions).mockResolvedValue({
      items: [versionFor(next)],
      total: 1,
      limit: 200,
      offset: 0,
    });
    vi.mocked(getVersion).mockResolvedValue({ version: versionFor(next) });
    view.rerender(view.tree(next));
    fireEvent.click(await screen.findByRole("tab", { name: "Change log" }));
    await waitFor(() => {
      const switched = vi
        .mocked(listEntityChangeLog)
        .mock.calls.filter((call) => call[0] === "ent_2");
      expect(switched.length).toBeGreaterThan(0);
      expect(switched.every((call) => call[1]?.cursor == null)).toBe(true);
      expect(switched.at(-1)?.[1]).toMatchObject({
        row_identity: "LEFT",
        version_id: "ver_kept",
        row_id: "4",
      });
    });
  });
});
