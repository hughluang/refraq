/** @vitest-environment jsdom */

import { MantineProvider } from "@mantine/core";
import { notifications, notificationsStore } from "@mantine/notifications";
import { cleanup, configure, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { createElement, type ReactNode } from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { ApiError } from "@/lib/api";
import en from "@/locales/en-US/common.json";
import { ConsoleNotifications } from "@/providers/notification-provider";

const listCatalogSources = vi.hoisted(() => vi.fn());
const listCatalogObjects = vi.hoisted(() => vi.fn());

const schedules = vi.hoisted(() => ({ listSourceSchedules: vi.fn(), runSchedule: vi.fn() }));
const mirrors = vi.hoisted(() => ({ listMirrors: vi.fn() }));
const location = vi.hoisted(() => ({ search: "" }));
vi.mock("@/features/schedules/api", () => schedules);
vi.mock("@/features/mirrors/api", () => mirrors);
configure({ asyncUtilTimeout: 7000 });

const copy = en as Record<string, string>;

function translate(key: string) {
  return copy[key] ?? key;
}

vi.mock("@refinedev/core", () => ({
  matchResourceFromRoute: () => ({ found: false }),
  useTranslate: () => translate,
  useCan: () => ({ data: { can: true }, isLoading: false }),
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
  useSearchParams: () => new URLSearchParams(location.search),
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
  return { ...actual, listCatalogSources, listCatalogObjects };
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
    const { CatalogBrowse } = await import("@/features/sources/CatalogBrowse");
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
    location.search = "";
    listCatalogSources.mockResolvedValue({ items: [{ id: "s1", name: "Sales", key: "sales" }], total: 1 });
    listCatalogObjects.mockResolvedValue({ items: [], total: 0 });
    schedules.listSourceSchedules.mockReset();
    schedules.runSchedule.mockReset();
    mirrors.listMirrors.mockReset();
  });
  afterEach(() => { cleanup(); resetNotifications(); });

  it("refreshes Source discovery after the first Source becomes visible", async () => {
    listCatalogSources.mockResolvedValueOnce({ items: [], total: 0 });
    schedules.listSourceSchedules.mockResolvedValue({ items: [], total: 0 });
    const { CatalogBrowse } = await import("./CatalogBrowse");
    render(shell(createElement(CatalogBrowse)));
    await screen.findByText(copy["catalog.list.noSources"]);
    fireEvent.click(screen.getByRole("button", { name: copy["catalog.refresh"] }));
    expect(await screen.findByText(copy["catalog.collect.contact"])).toBeTruthy();
  });

  it("keeps the selector when a bookmarked Source has become unavailable", async () => {
    location.search = "source=old";
    listCatalogObjects.mockRejectedValueOnce(new ApiError(404, "SOURCE_NOT_FOUND", "hidden"));
    const { CatalogBrowse } = await import("./CatalogBrowse");
    render(shell(createElement(CatalogBrowse)));
    expect(await screen.findByText(copy["catalog.list.sourceUnavailable"])).toBeTruthy();
    expect(screen.getByRole("button", { name: copy["catalog.fields.source"] })).toBeTruthy();
  });

  it("collects through the selected Source's existing structure schedule", async () => {
    const { CatalogBrowse } = await import("./CatalogBrowse");
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
    const { CatalogBrowse } = await import("./CatalogBrowse");
    render(shell(createElement(CatalogBrowse)));
    fireEvent.click((await screen.findAllByRole("button", { name: copy["common.filters.clear"] })).at(-1)!);
    expect(await screen.findByText(copy["catalog.collect.contact"])).toBeTruthy();
    expect(window.location.search).toBe("?source=s1");
    expect(screen.queryByRole("button", { name: copy["catalog.collect.action"] })).toBeNull();
  });

  it("shows the Operations empty state before any source mirror is provisioned", async () => {
    mirrors.listMirrors.mockResolvedValue({ items: [], total: 0 });
    const { MirrorList } = await import("../mirrors/MirrorList");
    render(shell(createElement(MirrorList)));
    expect(await screen.findByText(copy["mirrors.empty"])).toBeTruthy();
    expect(screen.queryByRole("link", { name: en["catalog.title"] })).toBeNull();
  });

  it("keeps filtered emptiness separate from a load failure and a revoked mirror permission", async () => {
    location.search = "q=missing";
    mirrors.listMirrors.mockResolvedValueOnce({ items: [], total: 0 })
      .mockRejectedValueOnce(new ApiError(500, "UNKNOWN", "offline"))
      .mockRejectedValueOnce(new ApiError(403, "FORBIDDEN", "revoked"));
    const { MirrorList } = await import("../mirrors/MirrorList");
    render(shell(createElement(MirrorList)));
    expect(await screen.findByText(copy["common.noMatch"])).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: copy["common.refresh"] }));
    fireEvent.click(await screen.findByRole("button", { name: copy["status.unloaded"] }));
    expect(await screen.findByText(copy["forbidden.back"])).toBeTruthy();
    expect(screen.queryByRole("link", { name: en["catalog.title"] })).toBeNull();
  });
});
