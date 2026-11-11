/** @vitest-environment jsdom */

import { MantineProvider } from "@mantine/core";
import { notifications, notificationsStore } from "@mantine/notifications";
import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { createElement, type ReactNode } from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { ApiError } from "@/lib/api";
import en from "@/locales/en-US/common.json";
import { ConsoleNotifications } from "@/providers/notification-provider";

const copy = en as Record<string, string>;
const search = vi.hoisted(() => ({ value: "" }));
const replace = vi.hoisted(() => vi.fn());
const gate = vi.hoisted(() => ({ canEdit: true, canDelete: true }));
const permissions = vi.hoisted(() => ({
  data: ["sources:read", "sources:write"] as string[],
}));
const getSource = vi.hoisted(() => vi.fn());
const listSources = vi.hoisted(() => vi.fn());
const listSourceMemberships = vi.hoisted(() => vi.fn());
const createSourceMembership = vi.hoisted(() => vi.fn());
const changeSourceMembership = vi.hoisted(() => vi.fn());
const deleteSourceMembership = vi.hoisted(() => vi.fn());
const userSearch = vi.hoisted(() => vi.fn());
const getSourceAccess = vi.hoisted(() => vi.fn());
const getAccessSchema = vi.hoisted(() => vi.fn());
const createSource = vi.hoisted(() => vi.fn());
const patchSource = vi.hoisted(() => vi.fn());
const deleteSource = vi.hoisted(() => vi.fn());
const listStructureDiffs = vi.hoisted(() => vi.fn());
const notify = vi.hoisted(() => vi.fn());

vi.mock("@/features/sources/api/sources", () => ({
  getSource: (...args: unknown[]) => getSource(...args),
  getSourceAccess: (...args: unknown[]) => getSourceAccess(...args),
  getAccessSchema: (...args: unknown[]) => getAccessSchema(...args),
  createSource: (...args: unknown[]) => createSource(...args),
  patchSource: (...args: unknown[]) => patchSource(...args),
  deleteSource: (...args: unknown[]) => deleteSource(...args),
  listSources: (...args: unknown[]) => listSources(...args),
  testSource: vi.fn(),
  testSourceDraft: vi.fn(),
}));

vi.mock("@/features/sources/api/memberships", () => ({
  listSourceMemberships: (...args: unknown[]) => listSourceMemberships(...args),
  createSourceMembership: (...args: unknown[]) => createSourceMembership(...args),
  changeSourceMembership: (...args: unknown[]) => changeSourceMembership(...args),
  deleteSourceMembership: (...args: unknown[]) => deleteSourceMembership(...args),
}));

vi.mock("@/components/form/recordPickerAdapters", () => ({
  userRecordAdapter: () => ({
    search: (...args: unknown[]) => userSearch(...args),
    resolve: async (ids: readonly string[]) =>
      ids.filter(Boolean).map((id) => ({ id, name: "Ada", key: "ada" })),
  }),
  userGroupRecordAdapter: () => ({
    search: async () => [],
    resolve: async () => [],
  }),
  roleRecordAdapter: () => ({
    search: async () => [],
    resolve: async () => [],
  }),
}));

vi.mock("@/features/sources/api/structure-diffs", () => ({
  listStructureDiffs: (...args: unknown[]) => listStructureDiffs(...args),
}));

vi.mock("@/features/branding/BrandingProvider", () => ({
  useBranding: () => ({ brandName: "Refraq" }),
}));

vi.mock("@/components/navigation/useConsoleNavigation", () => ({
  useConsoleNavigation: () => ({ push: vi.fn(), replace, refresh: vi.fn(), pending: false }),
}));

vi.mock("next/navigation", () => ({
  usePathname: () => "/console/sources/src_1",
  useRouter: () => ({ push: vi.fn(), replace, refresh: vi.fn() }),
  useSearchParams: () => new URLSearchParams(search.value),
}));

vi.mock("next/link", () => ({
  default: ({ href, children }: { href: string; children: ReactNode }) =>
    createElement("a", { href }, children),
  useLinkStatus: () => ({ pending: false }),
}));

vi.mock("@refinedev/core", () => ({
  matchResourceFromRoute: () => ({ found: false }),
  useTranslate: () => (key: string, options?: Record<string, unknown>) => {
    const template = copy[key] ?? key;
    if (!options) return template;
    return template.replace(/\{\{(\w+)\}\}/g, (_, name: string) => String(options[name] ?? ""));
  },
  useNotification: () => ({ open: notify }),
  useCan: ({ action }: { action?: string }) => ({
    data: { can: action === "delete" ? gate.canDelete : gate.canEdit },
  }),
  usePermissions: () => ({ data: permissions.data, isLoading: false }),
  useBreadcrumb: () => ({ breadcrumbs: [] }),
  CanAccess: ({ children }: { children?: ReactNode }) => children,
}));

const LEDGER = {
  id: "src_1",
  key: "ledger",
  locator_key: "ledger",
  name: "Ledger",
  kind: "database",
  status: "active",
  description: "",
  engine: "postgresql",
  access: { host: "db.internal" },
  has_access: true,
  access_updated_at: null,
};

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
  if (document.fonts == null) {
    Object.defineProperty(document, "fonts", {
      configurable: true,
      value: { addEventListener() {}, removeEventListener() {} },
    });
  }
}

function resetNotifications() {
  const state = notificationsStore.getState();
  for (const item of [...state.notifications, ...state.queue]) {
    notifications.hide(item.id);
  }
  notifications.clean();
}

function shell(node: ReactNode) {
  return createElement(
    MantineProvider,
    { env: "test" },
    createElement(ConsoleNotifications),
    node,
  );
}

function rejection(details: { field: string; message: string }[]) {
  return new ApiError(422, "REQUEST_INVALID", "Request validation failed", "req-source", {}, details);
}

function schema() {
  return { engine: "postgresql", schema: { type: "object", properties: {} } };
}

async function renderRecord(props: { mode: "create" } | { mode: "show" | "edit"; sourceId: string }) {
  const { SourceRecord } = await import("@/features/sources/SourceRecord");
  render(shell(createElement(SourceRecord, props)));
}

describe("SourceRecord", () => {
  beforeEach(() => {
    stubDomApis();
    search.value = "";
    gate.canEdit = true;
    gate.canDelete = true;
    replace.mockReset();
    notify.mockReset();
    permissions.data = ["sources:read", "sources:write"];
    getSource.mockReset();
    listSources.mockReset();
    listSourceMemberships.mockReset();
    createSourceMembership.mockReset();
    changeSourceMembership.mockReset();
    deleteSourceMembership.mockReset();
    userSearch.mockReset();
    listSourceMemberships.mockResolvedValue({ items: [] });
    userSearch.mockResolvedValue([{ id: "usr_ada", name: "Ada", key: "ada" }]);
    getSourceAccess.mockReset();
    getAccessSchema.mockReset();
    createSource.mockReset();
    patchSource.mockReset();
    deleteSource.mockReset();
    listStructureDiffs.mockReset();
    getSource.mockResolvedValue({ source: LEDGER });
    getSourceAccess.mockResolvedValue({ access: { host: "db.internal", password: "secret" } });
    getAccessSchema.mockResolvedValue(schema());
    listStructureDiffs.mockResolvedValue({
      items: [
        {
          id: "diff_1",
          source_id: "src_1",
          job_id: "job_1",
          class: "unchanged",
          counts: {},
          created_at: "2026-09-10T04:00:00Z",
        },
      ],
      total: 1,
      limit: 50,
      offset: 0,
    });
    resetNotifications();
  });

  afterEach(() => {
    cleanup();
    resetNotifications();
  });

  it("marks the mapped field, notifies once, and keeps the form free of an alert", async () => {
    createSource.mockRejectedValue(
      rejection([
        { field: "name", message: "Name is taken" },
        { field: "retired", message: "Unknown field" },
      ]),
    );
    await renderRecord({ mode: "create" });
    fireEvent.change(await screen.findByLabelText(/^Key/), { target: { value: "ledger" } });
    fireEvent.change(screen.getByLabelText(/^Name/), { target: { value: "Ledger" } });
    fireEvent.click(screen.getByRole("button", { name: copy["common.save"] }));

    expect(await screen.findAllByRole("alert")).toHaveLength(1);
    const form = document.querySelector("form");
    expect(form?.querySelector("[role='alert']")).toBeNull();
    expect((await screen.findAllByText("Name is taken")).length).toBeGreaterThan(0);
    fireEvent.click(screen.getByText(copy["form.error.details"]));
    const disclosure = screen.getByText(copy["form.error.details"]).closest("details");
    expect(disclosure?.textContent).toContain("retired: Unknown field");
    expect(disclosure?.textContent).not.toContain("Name is taken");
    expect(form?.textContent).not.toContain("Unknown field");
    expect(form?.textContent).not.toContain("Request validation failed");
  });

  it("marks every mapped field and sends no notification when the 422 is fully mapped", async () => {
    createSource.mockRejectedValue(rejection([{ field: "name", message: "Name is taken" }]));
    await renderRecord({ mode: "create" });
    fireEvent.change(await screen.findByLabelText(/^Key/), { target: { value: "ledger" } });
    fireEvent.change(screen.getByLabelText(/^Name/), { target: { value: "Ledger" } });
    fireEvent.click(screen.getByRole("button", { name: copy["common.save"] }));

    expect((await screen.findAllByText("Name is taken")).length).toBeGreaterThan(0);
    expect(screen.queryByRole("alert")).toBeNull();
    expect(document.querySelector("form")?.querySelector("[role='alert']")).toBeNull();
    expect(screen.queryByText(copy["form.error.details"])).toBeNull();
  });

  it("shows fields as text and keeps a reader off the edit route", async () => {
    gate.canEdit = false;
    await renderRecord({ mode: "show", sourceId: "src_1" });

    expect(await screen.findByRole("heading", { name: "Ledger" })).toBeTruthy();
    expect(screen.queryByRole("textbox")).toBeNull();
    expect(screen.queryByRole("combobox")).toBeNull();
    expect(screen.queryByRole("button", { name: copy["common.save"] })).toBeNull();
    expect(screen.queryByRole("link", { name: copy["sources.edit"] })).toBeNull();
    expect(getSourceAccess).not.toHaveBeenCalled();
  });

  it("keeps the key visible and saves an edit without leaving the page", async () => {
    patchSource.mockResolvedValue({ source: { ...LEDGER, name: "Ledger West" } });
    await renderRecord({ mode: "edit", sourceId: "src_1" });

    const name = await screen.findByLabelText(/^Name/);
    expect(screen.queryByRole("textbox", { name: /^Key/ })).toBeNull();
    expect(screen.getByText("ledger")).toBeTruthy();
    expect(screen.getByRole("combobox", { name: /^Status/ })).toBeTruthy();
    fireEvent.change(name, { target: { value: "Ledger West" } });
    fireEvent.click(screen.getByRole("button", { name: copy["common.save"] }));

    await waitFor(() => expect(patchSource).toHaveBeenCalled());
    expect(patchSource).toHaveBeenCalledWith(
      "src_1",
      expect.objectContaining({
        name: "Ledger West",
        status: "active",
        engine: "postgresql",
        access: { host: "db.internal", password: "secret" },
      }),
    );
    expect(replace).not.toHaveBeenCalled();
    expect(getSourceAccess).toHaveBeenCalledWith("src_1");
  });

  it("sends an edit visit without write permission back to show and keeps the tab", async () => {
    gate.canEdit = false;
    search.value = "tab=diffs";
    await renderRecord({ mode: "edit", sourceId: "src_1" });

    await waitFor(() =>
      expect(replace).toHaveBeenCalledWith("/console/sources/src_1?tab=diffs"),
    );
    expect(getSource).not.toHaveBeenCalled();
    expect(getSourceAccess).not.toHaveBeenCalled();
    expect(screen.queryByRole("textbox")).toBeNull();
  });

  it("keeps the edit form mounted while the diffs tab is selected", async () => {
    search.value = "tab=diffs";
    patchSource.mockResolvedValue({ source: LEDGER });
    await renderRecord({ mode: "edit", sourceId: "src_1" });

    const diffs = await screen.findByRole("tab", { name: copy["structureDiffs.title"] });
    expect(diffs.getAttribute("aria-selected")).toBe("true");
    expect(screen.getByLabelText(/^Name/, { selector: "input", hidden: true })).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: copy["common.save"] }));
    await waitFor(() => expect(patchSource).toHaveBeenCalled());
  });

  it("shows delete on show and edit when the actor can delete", async () => {
    await renderRecord({ mode: "show", sourceId: "src_1" });
    const showDelete = await screen.findByRole("button", { name: copy["sources.delete"] });
    expect((showDelete as HTMLButtonElement).disabled).toBe(true);
    cleanup();

    await renderRecord({ mode: "edit", sourceId: "src_1" });
    const editDelete = await screen.findByRole("button", { name: copy["sources.delete"] });
    expect((editDelete as HTMLButtonElement).disabled).toBe(true);
  });

  it("hides delete on show and edit when the actor cannot delete", async () => {
    gate.canDelete = false;
    await renderRecord({ mode: "show", sourceId: "src_1" });
    expect(await screen.findByRole("heading", { name: "Ledger" })).toBeTruthy();
    expect(screen.queryByRole("button", { name: copy["sources.delete"] })).toBeNull();
    cleanup();

    await renderRecord({ mode: "edit", sourceId: "src_1" });
    expect(await screen.findByRole("button", { name: copy["common.save"] })).toBeTruthy();
    expect(screen.queryByRole("button", { name: copy["sources.delete"] })).toBeNull();
  });

  it("confirms delete of a disabled source and returns to the list", async () => {
    getSource.mockResolvedValue({ source: { ...LEDGER, status: "disabled" } });
    deleteSource.mockResolvedValue(undefined);
    const assign = vi.fn();
    const prior = window.location;
    Object.defineProperty(window, "location", {
      configurable: true,
      value: { assign, href: prior.href },
    });
    try {
      await renderRecord({ mode: "show", sourceId: "src_1" });

      fireEvent.click(await screen.findByRole("button", { name: copy["sources.delete"] }));
      const dialog = await screen.findByRole("dialog", {
        name: copy["sources.delete.confirmTitle"],
      });
      expect(within(dialog).getByText(copy["sources.delete.consequence"])).toBeTruthy();
      fireEvent.click(within(dialog).getByRole("button", { name: copy["sources.delete"] }));

      await waitFor(() => expect(deleteSource).toHaveBeenCalledWith("src_1"));
      await waitFor(() => expect(assign).toHaveBeenCalledWith("/console/sources"));
    } finally {
      Object.defineProperty(window, "location", { configurable: true, value: prior });
    }
  });

  it("lists this source's diffs and links each one to the detail route", async () => {
    await renderRecord({ mode: "show", sourceId: "src_1" });
    fireEvent.click(await screen.findByRole("tab", { name: copy["structureDiffs.title"] }));

    await waitFor(() => {
      expect(
        document.querySelector('a[href="/console/sources/src_1/structure-diffs/diff_1"]'),
      ).toBeTruthy();
    });
    expect(listStructureDiffs).toHaveBeenCalled();
  });

  it("shows members to a manager and writes a user at viewer", async () => {
    permissions.data = ["sources:read", "sources:write", "sources:access_manage"];
    listSourceMemberships.mockResolvedValue({
      items: [
        {
          id: "mem_ada",
          subject: { type: "user", id: "usr_ada", display_name: "Ada", missing: false },
          target: "src_1",
          level: "steward",
          created_at: "2026-09-10T04:00:00Z",
          updated_at: "2026-09-10T04:00:00Z",
        },
      ],
    });
    createSourceMembership.mockResolvedValue({ membership: { id: "mem_new" } });
    await renderRecord({ mode: "show", sourceId: "src_1" });

    fireEvent.click(await screen.findByRole("tab", { name: copy["sources.tabs.members"] }));
    expect(await screen.findByText("Ada")).toBeTruthy();
    expect(screen.getByText(copy["sources.membership.level.steward"])).toBeTruthy();

    fireEvent.click(screen.getByRole("button", { name: copy["sources.membership.add"] }));
    const dialog = await screen.findByRole("dialog", { name: copy["sources.membership.add"] });
    const level = within(dialog).getByRole("combobox", { name: copy["sources.membership.level"] });
    fireEvent.mouseDown(level);
    const levelList = screen.getAllByRole("listbox", { hidden: true }).find((list) =>
      within(list).queryByRole("option", {
        name: copy["sources.membership.level.viewer"],
        hidden: true,
      }),
    );
    expect(levelList).toBeTruthy();
    expect(
      within(levelList!).getAllByRole("option", { hidden: true }).map((option) => option.textContent),
    ).toEqual([
      copy["sources.membership.level.viewer"],
      copy["sources.membership.level.steward"],
      copy["sources.membership.level.maintainer"],
    ]);
    fireEvent.click(within(dialog).getByRole("button", { name: /^Subject/ }));
    fireEvent.click(await screen.findByRole("option", { name: /Ada/, hidden: true }));
    fireEvent.click(within(dialog).getByRole("button", { name: copy["sources.membership.add"] }));

    await waitFor(() => expect(createSourceMembership).toHaveBeenCalled());
    expect(createSourceMembership).toHaveBeenCalledWith("src_1", {
      subject: { type: "user", id: "usr_ada" },
      level: "viewer",
    });
  });

  it("changes and deletes a membership through the source routes", async () => {
    permissions.data = ["sources:access_manage", "sources:read"];
    listSourceMemberships.mockResolvedValue({
      items: [
        {
          id: "mem_ada",
          subject: { type: "role", id: "role_1", display_name: "Analyst", missing: false },
          target: "src_1",
          level: "viewer",
          created_at: "2026-09-10T04:00:00Z",
          updated_at: "2026-09-10T04:00:00Z",
        },
      ],
    });
    changeSourceMembership.mockResolvedValue({ membership: { id: "mem_ada" } });
    deleteSourceMembership.mockResolvedValue(undefined);
    await renderRecord({ mode: "show", sourceId: "src_1" });
    fireEvent.click(await screen.findByRole("tab", { name: copy["sources.tabs.members"] }));
    fireEvent.click(await screen.findByRole("button", { name: copy["sources.membership.change"] }));
    const dialog = await screen.findByRole("dialog", { name: copy["sources.membership.change"] });
    expect(within(dialog).getByText("Analyst")).toBeTruthy();
    expect(within(dialog).queryByRole("combobox", { name: copy["sources.membership.subjectKind"] })).toBeNull();
    fireEvent.mouseDown(within(dialog).getByRole("combobox", { name: copy["sources.membership.level"] }));
    fireEvent.click(
      screen.getByRole("option", { name: copy["sources.membership.level.steward"], hidden: true }),
    );
    fireEvent.click(within(dialog).getByRole("button", { name: copy["sources.membership.change"] }));
    await waitFor(() =>
      expect(changeSourceMembership).toHaveBeenCalledWith("src_1", "mem_ada", "steward"),
    );

    fireEvent.click(screen.getByRole("button", { name: copy["sources.membership.remove"] }));
    const confirm = await screen.findByRole("dialog", { name: copy["sources.membership.removeTitle"] });
    fireEvent.click(within(confirm).getByRole("button", { name: copy["sources.membership.remove"] }));
    await waitFor(() => expect(deleteSourceMembership).toHaveBeenCalledWith("src_1", "mem_ada"));
  });

  it("lets a maintainer read members and hides write controls", async () => {
    listSourceMemberships.mockResolvedValue({
      items: [
        {
          id: "mem_ada",
          subject: { type: "user", id: "usr_ada", display_name: "Ada", missing: false },
          target: "src_1",
          level: "viewer",
          created_at: "2026-09-10T04:00:00Z",
          updated_at: "2026-09-10T04:00:00Z",
        },
      ],
    });
    await renderRecord({ mode: "show", sourceId: "src_1" });

    fireEvent.click(await screen.findByRole("tab", { name: copy["sources.tabs.members"] }));
    expect(await screen.findByText("Ada")).toBeTruthy();
    expect(screen.queryByRole("button", { name: copy["sources.membership.add"] })).toBeNull();
    expect(screen.queryByRole("button", { name: copy["sources.membership.change"] })).toBeNull();
    expect(screen.queryByRole("button", { name: copy["sources.membership.remove"] })).toBeNull();
  });

  it("labels a missing subject and offers only delete to a manager", async () => {
    permissions.data = ["sources:access_manage", "sources:read"];
    listSourceMemberships.mockResolvedValue({
      items: [
        {
          id: "mem_gone",
          subject: { type: "group", id: "grp_gone", display_name: null, missing: true },
          target: "src_1",
          level: "viewer",
          created_at: "2026-09-10T04:00:00Z",
          updated_at: "2026-09-10T04:00:00Z",
        },
      ],
    });
    await renderRecord({ mode: "edit", sourceId: "src_1" });

    fireEvent.click(await screen.findByRole("tab", { name: copy["sources.tabs.members"] }));
    expect(await screen.findByText(copy["sources.membership.subjectMissing"])).toBeTruthy();
    expect(screen.queryByRole("button", { name: copy["sources.membership.change"] })).toBeNull();
    expect(screen.getByRole("button", { name: copy["sources.membership.remove"] })).toBeTruthy();
  });

  it("omits the members tab when the caller cannot list memberships", async () => {
    listSourceMemberships.mockRejectedValue(
      new ApiError(403, "AUTH_FORBIDDEN", "Membership list refused"),
    );
    await renderRecord({ mode: "show", sourceId: "src_1" });

    expect(await screen.findByRole("heading", { name: "Ledger" })).toBeTruthy();
    await waitFor(() => expect(listSourceMemberships).toHaveBeenCalledWith("src_1"));
    expect(screen.queryByRole("tab", { name: copy["sources.tabs.members"] })).toBeNull();
    expect(screen.queryByRole("button", { name: copy["sources.membership.add"] })).toBeNull();
  });

  it("shows identity fields for access manage without opening the access document", async () => {
    permissions.data = ["sources:access_manage"];
    gate.canEdit = false;
    listSources.mockResolvedValue({
      items: [
        {
          id: "src_1",
          key: "ledger",
          name: "Ledger",
          kind: "database",
          engine: "postgresql",
          status: "active",
        },
      ],
      total: 1,
      limit: 100,
      offset: 0,
    });
    await renderRecord({ mode: "show", sourceId: "src_1" });

    expect(await screen.findByRole("tab", { name: copy["sources.tabs.members"] })).toBeTruthy();
    expect(screen.getByText("ledger")).toBeTruthy();
    expect(screen.getByText(copy["sources.engines.postgresql"])).toBeTruthy();
    expect(screen.getByText(copy["sources.status.active"])).toBeTruthy();
    expect(screen.queryByText(copy["sources.spec.section"])).toBeNull();
    expect(screen.queryByRole("button", { name: copy["sources.test"] })).toBeNull();
    expect(screen.queryByRole("tab", { name: copy["structureDiffs.title"] })).toBeNull();
    expect(screen.queryByLabelText(copy["sources.fields.description"])).toBeNull();
    expect(document.querySelector('a[href*="structure-diffs"]')).toBeNull();
    expect(document.querySelector('a[href*="/console/catalog"]')).toBeNull();
    expect(getSource).not.toHaveBeenCalled();
    expect(getSourceAccess).not.toHaveBeenCalled();
    expect(getAccessSchema).not.toHaveBeenCalled();
  });

  it("keeps an identity record in display mode on the edit route", async () => {
    permissions.data = ["sources:access_manage", "sources:write"];
    listSources.mockResolvedValue({
      items: [
        {
          id: "src_1",
          key: "ledger",
          name: "Ledger",
          kind: "database",
          engine: "postgresql",
          status: "active",
        },
      ],
      total: 1,
      limit: 100,
      offset: 0,
    });
    await renderRecord({ mode: "edit", sourceId: "src_1" });

    expect(await screen.findByRole("heading", { name: "Ledger" })).toBeTruthy();
    expect(screen.queryByRole("button", { name: copy["common.save"] })).toBeNull();
    expect(screen.queryByRole("link", { name: copy["sources.edit"] })).toBeNull();
    expect(document.querySelector("form")).toBeNull();
    expect(getSource).not.toHaveBeenCalled();
    expect(getAccessSchema).not.toHaveBeenCalled();
  });

  it("does not describe a refused membership list as an empty tab", async () => {
    let calls = 0;
    listSourceMemberships.mockImplementation(() => {
      calls += 1;
      if (calls === 1) return Promise.resolve({ items: [] });
      return Promise.reject(new ApiError(403, "AUTH_FORBIDDEN", "Membership list refused"));
    });
    await renderRecord({ mode: "show", sourceId: "src_1" });

    fireEvent.click(await screen.findByRole("tab", { name: copy["sources.tabs.members"] }));
    expect(await screen.findByText(copy["problems.unknown"])).toBeTruthy();
    expect(screen.getByRole("heading", { name: "Ledger" })).toBeTruthy();
    expect(screen.queryByText(copy["sources.membership.empty"])).toBeNull();
    expect(screen.queryByRole("button", { name: copy["status.unloaded"] })).toBeNull();
  });

  it("shows not-found when a reader has no level, without a retry notice", async () => {
    permissions.data = ["sources:read"];
    getSource.mockRejectedValue(
      new ApiError(404, "SOURCE_NOT_FOUND", "Source not found", "req-absent"),
    );
    await renderRecord({ mode: "show", sourceId: "src_1" });

    expect(await screen.findByRole("heading", { name: copy["layout.notFound.title"] })).toBeTruthy();
    expect(screen.queryByRole("button", { name: copy["status.unloaded"] })).toBeNull();
    expect(screen.queryByText(copy["problems.unknown"])).toBeNull();
    expect(screen.queryByText("Source not found")).toBeNull();
    expect(screen.queryByText("Ledger")).toBeNull();
    expect(listSources).not.toHaveBeenCalled();
    expect(getAccessSchema).not.toHaveBeenCalled();
  });

  it("keeps a reader load failure as unloaded with one retry notice", async () => {
    permissions.data = ["sources:read"];
    getSource.mockRejectedValue(new ApiError(500, "NO_SUCH_CODE", "boom", "req-down"));
    await renderRecord({ mode: "show", sourceId: "src_1" });

    expect(await screen.findByRole("button", { name: copy["status.unloaded"] })).toBeTruthy();
    expect(await screen.findByText(copy["problems.unknown"])).toBeTruthy();
    expect(screen.queryByRole("heading", { name: copy["layout.notFound.title"] })).toBeNull();
    expect(screen.getByText(`${copy["common.requestId"]}: req-down`)).toBeTruthy();
  });

  it("shows an identity row when access manage can list a source the read missed", async () => {
    permissions.data = ["sources:access_manage", "sources:read"];
    gate.canEdit = false;
    getSource.mockRejectedValue(
      new ApiError(404, "SOURCE_NOT_FOUND", "Source not found", "req-hidden"),
    );
    listSources.mockResolvedValue({
      items: [
        {
          id: "src_1",
          key: "ledger",
          name: "Ledger",
          kind: "database",
          engine: "postgresql",
          status: "active",
        },
      ],
      total: 1,
      limit: 100,
      offset: 0,
    });
    await renderRecord({ mode: "show", sourceId: "src_1" });

    expect(await screen.findByRole("heading", { name: "Ledger" })).toBeTruthy();
    expect(screen.getByText("ledger")).toBeTruthy();
    expect(screen.getByText(copy["sources.engines.postgresql"])).toBeTruthy();
    expect(screen.queryByRole("heading", { name: copy["layout.notFound.title"] })).toBeNull();
    expect(screen.queryByText(copy["problems.unknown"])).toBeNull();
    expect(getSourceAccess).not.toHaveBeenCalled();
    expect(getAccessSchema).not.toHaveBeenCalled();
  });

  it("shows not-found when access manage cannot list the missing source either", async () => {
    permissions.data = ["sources:access_manage", "sources:read"];
    getSource.mockRejectedValue(
      new ApiError(404, "SOURCE_NOT_FOUND", "Source not found", "req-missing"),
    );
    listSources.mockResolvedValue({ items: [], total: 0, limit: 100, offset: 0 });
    await renderRecord({ mode: "show", sourceId: "src_1" });

    expect(await screen.findByRole("heading", { name: copy["layout.notFound.title"] })).toBeTruthy();
    expect(screen.queryByRole("button", { name: copy["status.unloaded"] })).toBeNull();
    expect(screen.queryByText(copy["problems.unknown"])).toBeNull();
    expect(listSources).toHaveBeenCalled();
  });
});
