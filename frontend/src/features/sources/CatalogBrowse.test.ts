/** @vitest-environment jsdom */

import { MantineProvider } from "@mantine/core";
import { notifications, notificationsStore } from "@mantine/notifications";
import { cleanup, configure, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { createElement, type ReactNode } from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { MirrorList } from "@/features/mirrors/MirrorList";
import { CatalogBrowse } from "./CatalogBrowse";
import { ApiError } from "@/lib/api";
import en from "@/locales/en-US/common.json";
import { ConsoleNotifications } from "@/providers/notification-provider";

const listCatalogSources = vi.hoisted(() => vi.fn());
const listCatalogObjects = vi.hoisted(() => vi.fn());
const listMirrorTables = vi.hoisted(() => vi.fn());
const setCatalogMirrorEnabled = vi.hoisted(() => vi.fn());
const grants = vi.hoisted(() => ({ readMirror: true }));

const schedules = vi.hoisted(() => ({ listSourceSchedules: vi.fn(), runSchedule: vi.fn() }));
const mirrors = vi.hoisted(() => ({ listMirrors: vi.fn(), getMirror: vi.fn() }));
const location = vi.hoisted(() => ({ search: "" as string | null }));
vi.mock("@/features/schedules/api", () => schedules);
vi.mock("@/features/mirrors/api", () => mirrors);
configure({ asyncUtilTimeout: 7000 });

const copy = en as Record<string, string>;

function translate(key: string, args?: { table?: string }) {
  return (copy[key] ?? key).replace("{{table}}", args?.table ?? "{{table}}");
}

vi.mock("@refinedev/core", () => ({
  matchResourceFromRoute: () => ({ found: false }),
  useTranslate: () => translate,
  useCan: ({ resource, action }: { resource: string; action: string }) => ({
    data: { can: resource !== "mirrors" || action !== "show" || grants.readMirror },
    isLoading: false,
  }),
  useBreadcrumb: () => ({ breadcrumbs: [] }),
}));

vi.mock("next/link", () => ({
  default: ({ href, children }: { href: string; children: ReactNode }) =>
    createElement("a", { href }, children),
  useLinkStatus: () => ({ pending: false }),
}));

vi.mock("next/navigation", () => ({
  usePathname: () => "/console/catalog",
  useRouter: () => ({ push: vi.fn(), replace: vi.fn(), refresh: vi.fn() }),
  useSearchParams: () => new URLSearchParams(location.search ?? window.location.search),
}));

vi.mock("@/features/branding/BrandingProvider", () => ({
  useBranding: () => ({ brandName: "Refraq" }),
}));

vi.mock("@/providers/session-store", () => ({
  useSessionStore: (selector: (state: { user: null }) => unknown) =>
    selector({ user: null }),
}));

vi.mock("@/features/sources/api/catalog", async () => {
  const actual = await vi.importActual<typeof import("@/features/sources/api/catalog")>(
    "@/features/sources/api/catalog",
  );
  return { ...actual, listCatalogSources, listCatalogObjects, listMirrorTables, setCatalogMirrorEnabled };
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

describe("CatalogBrowse source probe", () => {
  beforeEach(() => {
    window.history.replaceState(null, "", "/console/catalog");
    location.search = "";
    stubDomApis();
    listCatalogSources.mockReset();
    listCatalogObjects.mockReset();
    listCatalogObjects.mockResolvedValue({ items: [], total: 0, limit: 100, offset: 0 });
    resetNotifications();
  });

  afterEach(() => {
    cleanup();
    resetNotifications();
  });

  it("keeps the catalog header and shows one retryable notice when the source probe fails", async () => {
    listCatalogSources.mockRejectedValue(
      new ApiError(500, "NO_SUCH_CODE", "database offline", "req-18"),
    );
    render(shell(createElement(CatalogBrowse)));

    const heading = await screen.findByRole("heading", { name: "Catalog" });
    expect(document.querySelector("[data-page-header]")?.contains(heading)).toBe(true);
    expect(screen.getByRole("button", { name: "Not loaded" })).toBeTruthy();
    expect(screen.queryByText("No Sources")).toBeNull();
    expect(screen.queryByText("No catalog objects for this Source")).toBeNull();
    expect(screen.queryByText("Something went wrong")).toBeNull();

    expect(await screen.findAllByRole("alert")).toHaveLength(1);
    fireEvent.click(screen.getByText("Details"));
    expect(screen.getByText("database offline").closest("details")).toBeTruthy();
    expect(screen.getByText("Request ID: req-18").closest("details")).toBeTruthy();

    fireEvent.click(screen.getByRole("button", { name: "Retry" }));
    await waitFor(() => expect(listCatalogSources).toHaveBeenCalledTimes(2));
    expect(listCatalogObjects).not.toHaveBeenCalled();
  });
});

describe("Source and Operations discovery", () => {
  beforeEach(() => {
    stubDomApis();
    window.history.replaceState(null, "", "/console/catalog");
    location.search = "";
    grants.readMirror = true;
    listCatalogSources.mockResolvedValue({ items: [{ id: "s1", name: "Sales", key: "sales" }], total: 1 });
    listCatalogObjects.mockResolvedValue({ items: [], total: 0 });
    schedules.listSourceSchedules.mockReset();
    schedules.runSchedule.mockReset();
    mirrors.listMirrors.mockReset();
    mirrors.getMirror.mockReset();
    listMirrorTables.mockReset();
    setCatalogMirrorEnabled.mockReset();
  });
  afterEach(() => { cleanup(); resetNotifications(); });

  it("lets a write-only Mirror operator enable a table through the filtered Catalog picker", async () => {
    grants.readMirror = false;
    location.search = null;
    window.history.replaceState(null, "", "/console/catalog?source=s1");
    const source = { id: "s1", key: "sales", name: "Sales" };
    const row = { object_id: "orders", source_id: source.id, source_key: source.key, source_name: source.name,
      qualified_table: "public.orders_10", storage_destination: "source_mirror", estimated_rows: 0,
      source_size_bytes: 8192, mirror: { enabled: false, can_enable: true, can_disable: false, mirror_id: null },
      snapshot_holder: null };
    listMirrorTables.mockResolvedValue({ items: [row], total: 1, offset: 0, limit: 10 });
    setCatalogMirrorEnabled.mockResolvedValue({
      operation_id: "accepted-open", mirror: { enabled: true, can_enable: false, can_disable: true, mirror_id: null },
    });
    schedules.listSourceSchedules.mockResolvedValue({ items: [], total: 0 });
    render(shell(createElement(CatalogBrowse)));
    fireEvent.click(screen.getByRole("button", { name: copy["mirrors.chooseTable"] }));
    const drawer = within(await screen.findByRole("dialog"));
    const search = drawer.getByRole("textbox", { name: copy["mirrors.tableSearch"] });
    fireEvent.change(search, { target: { value: "public.orders_10" } });
    await waitFor(() => expect(listMirrorTables).toHaveBeenCalledWith({
      source_id: source.id, q: "public.orders_10", offset: 0, limit: 10,
    }));
    fireEvent.click(await drawer.findByRole("button", { name: row.qualified_table }));
    fireEvent.click(await drawer.findByRole("switch"));
    expect(await drawer.findByText("accepted-open")).toBeTruthy();
    expect(drawer.getByRole("switch", { checked: true })).toBeTruthy();
    expect((await screen.findByRole("alert")).textContent).toContain(row.qualified_table);
    expect(drawer.queryByRole("link")).toBeNull();
    expect(mirrors.getMirror).not.toHaveBeenCalled();
  });

  it("refreshes Source discovery after the first Source becomes visible", async () => {
    listCatalogSources.mockResolvedValueOnce({ items: [], total: 0 });
    schedules.listSourceSchedules.mockResolvedValue({ items: [], total: 0 });
    render(shell(createElement(CatalogBrowse)));
    await screen.findByText(copy["catalog.list.noSources"]);
    fireEvent.click(screen.getByRole("button", { name: copy["catalog.refresh"] }));
    expect(await screen.findByText(copy["catalog.collect.contact"])).toBeTruthy();
  });

  it("keeps the selector when a bookmarked Source has become unavailable", async () => {
    location.search = "source=old";
    listCatalogObjects.mockRejectedValueOnce(new ApiError(404, "SOURCE_NOT_FOUND", "hidden"));
    render(shell(createElement(CatalogBrowse)));
    expect(await screen.findByText(copy["catalog.list.sourceUnavailable"])).toBeTruthy();
    expect(screen.getByRole("button", { name: copy["catalog.fields.source"] })).toBeTruthy();
  });

  it("collects through the selected Source's existing structure schedule", async () => {
    schedules.listSourceSchedules.mockResolvedValue({ items: [{ id: "s7", work_kind: "structure" }], total: 1 });
    schedules.runSchedule.mockResolvedValue({ job: { id: "j7" } });
    render(shell(createElement(CatalogBrowse)));
    fireEvent.click(await screen.findByRole("button", { name: copy["catalog.collect.action"] }));
    expect(await screen.findByText(copy["catalog.collect.queued"])).toBeTruthy();
    expect(schedules.runSchedule).toHaveBeenCalledWith("s7");
  });

  it("preserves the selected Source when clearing filters and explains collection authority", async () => {
    location.search = "source=s1&q=missing";
    schedules.listSourceSchedules.mockRejectedValue(new ApiError(404, "SOURCE_NOT_FOUND", "hidden"));
    render(shell(createElement(CatalogBrowse)));
    fireEvent.click((await screen.findAllByRole("button", { name: copy["common.filters.clear"] })).at(-1)!);
    expect(await screen.findByText(copy["catalog.collect.contact"])).toBeTruthy();
    expect(window.location.search).toBe("?source=s1");
    expect(screen.queryByRole("button", { name: copy["catalog.collect.action"] })).toBeNull();
  });

  it("shows the Operations empty state before any source mirror is provisioned", async () => {
    mirrors.listMirrors.mockResolvedValue({ items: [], total: 0 });
    render(shell(createElement(MirrorList)));
    expect(await screen.findByText(copy["mirrors.empty"])).toBeTruthy();
    expect(screen.queryByRole("link", { name: en["catalog.title"] })).toBeNull();
  });

  it("keeps filtered emptiness separate from a load failure and a revoked mirror permission", async () => {
    location.search = "q=missing";
    mirrors.listMirrors.mockResolvedValueOnce({ items: [], total: 0 })
      .mockRejectedValueOnce(new ApiError(500, "UNKNOWN", "offline"))
      .mockRejectedValueOnce(new ApiError(403, "FORBIDDEN", "revoked"));
    render(shell(createElement(MirrorList)));
    expect(await screen.findByText(copy["common.noMatch"])).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: copy["common.refresh"] }));
    fireEvent.click(await screen.findByRole("button", { name: copy["status.unloaded"] }));
    expect(await screen.findByText(copy["forbidden.back"])).toBeTruthy();
    expect(screen.queryByRole("link", { name: en["catalog.title"] })).toBeNull();
  });
});
