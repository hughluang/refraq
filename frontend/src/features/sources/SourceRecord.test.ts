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
const getSource = vi.hoisted(() => vi.fn());
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
  listSources: vi.fn(),
  testSource: vi.fn(),
  testSourceDraft: vi.fn(),
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
  useTranslate: () => (key: string, options?: Record<string, unknown>) => {
    const template = copy[key] ?? key;
    if (!options) return template;
    return template.replace(/\{\{(\w+)\}\}/g, (_, name: string) => String(options[name] ?? ""));
  },
  useNotification: () => ({ open: notify }),
  useCan: ({ action }: { action?: string }) => ({
    data: { can: action === "delete" ? gate.canDelete : gate.canEdit },
  }),
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
    getSource.mockReset();
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
});
