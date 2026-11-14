/** @vitest-environment jsdom */

import { MantineProvider } from "@mantine/core";
import { notifications, notificationsStore } from "@mantine/notifications";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { createElement, type ReactNode } from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { ApiError } from "@/lib/api";
import en from "@/locales/en-US/common.json";
import { ConsoleNotifications } from "@/providers/notification-provider";

const getCatalogObject = vi.hoisted(() => vi.fn());

const copy = en as Record<string, string>;

function translate(key: string) {
  return copy[key] ?? key;
}

vi.mock("@refinedev/core", () => ({
  matchResourceFromRoute: () => ({ found: false }),
  useTranslate: () => translate,
  useNotification: () => ({ open: vi.fn() }),
  useCan: () => ({ data: { can: false }, isLoading: false }),
  useBreadcrumb: () => ({ breadcrumbs: [] }),
}));

vi.mock("next/link", () => ({
  default: ({ href, children }: { href: string; children: ReactNode }) =>
    createElement("a", { href }, children),
  useLinkStatus: () => ({ pending: false }),
}));

vi.mock("next/navigation", () => ({
  usePathname: () => "/console/catalog/obj_1",
  useRouter: () => ({ push: vi.fn(), replace: vi.fn(), refresh: vi.fn() }),
  useSearchParams: () => new URLSearchParams(),
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
  return { ...actual, resolveCatalogObject: getCatalogObject };
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

describe("CatalogObjectDetail load", () => {
  beforeEach(() => {
    stubDomApis();
    getCatalogObject.mockReset();
    resetNotifications();
  });

  afterEach(() => {
    cleanup();
    resetNotifications();
  });

  it("shows unloaded and one notice with the request id when the object fails to load", async () => {
    getCatalogObject.mockRejectedValue(
      new ApiError(500, "NO_SUCH_CODE", "database offline", "req-18"),
    );
    const { CatalogObjectDetail } = await import(
      "@/features/sources/catalog-detail/CatalogObjectDetail"
    );
    render(shell(createElement(CatalogObjectDetail, { objectId: "obj_1" })));

    const heading = await screen.findByRole("heading", { name: "Details" });
    expect(document.querySelector("[data-page-header]")?.contains(heading)).toBe(true);
    expect(screen.getByRole("button", { name: "Not loaded" })).toBeTruthy();
    expect(screen.queryByRole("heading", { name: "Page not found" })).toBeNull();
    expect(screen.queryByText("Something went wrong")).toBeNull();

    expect(await screen.findAllByRole("alert")).toHaveLength(1);
    fireEvent.click(screen.getByText("Details", { selector: "summary" }));
    expect(screen.getByText("database offline").closest("details")).toBeTruthy();
    expect(screen.getByText("Request ID: req-18").closest("details")).toBeTruthy();

    fireEvent.click(screen.getByRole("button", { name: "Retry" }));
    await waitFor(() => expect(getCatalogObject).toHaveBeenCalledTimes(2));
  });

  it("keeps supplementary object metadata available behind a compact disclosure", async () => {
    getCatalogObject.mockResolvedValue({ object: {
      id: "obj_1", source_id: "source", schema_name: "public", name: "orders",
      object_type: "table", locator_key: "obj/postgresql/demo/public/table/orders",
      columns: [], is_present: true, business_semantics_ready: false,
    } });
    const { CatalogObjectDetail } = await import("@/features/sources/catalog-detail/CatalogObjectDetail");
    render(shell(createElement(CatalogObjectDetail, { objectId: "obj_1" })));
    await screen.findByRole("heading", { name: "public.orders" });
    const locator = screen.getByText("obj/postgresql/demo/public/table/orders");
    const details = locator.closest("details")!;
    expect(details.open).toBe(false);
    expect(details.querySelector("summary")?.textContent).toContain("Present");
    fireEvent.click(details.querySelector("summary")!);
    expect(details.open).toBe(true);
    expect(screen.getByRole("button", { name: "Copy locator" })).toBeTruthy();
    expect(screen.getByRole("tablist").style.flexWrap).toBe("nowrap");
  });

  it("ignores a prior object's late response after navigation", async () => {
    let finish!: (value: unknown) => void;
    getCatalogObject.mockImplementationOnce(() => new Promise((resolve) => { finish = resolve; }));
    getCatalogObject.mockResolvedValue({ object: {
      id: "new", source_id: "source", schema_name: "public", name: "new",
      object_type: "table", locator_key: "obj/postgresql/demo/public/table/new",
      columns: [], is_present: true,
    } });
    const { CatalogObjectDetail } = await import("@/features/sources/catalog-detail/CatalogObjectDetail");
    const view = render(shell(createElement(CatalogObjectDetail, { objectId: "old" })));
    view.rerender(shell(createElement(CatalogObjectDetail, { objectId: "new" })));
    await screen.findByRole("heading", { name: "public.new" });
    expect(getCatalogObject.mock.calls[0][1].aborted).toBe(true);
    finish({ object: { id: "old", schema_name: "public", name: "old", columns: [] } });
    await waitFor(() => expect(screen.getByRole("heading", { name: "public.new" })).toBeTruthy());
    expect(screen.queryByRole("heading", { name: "public.old" })).toBeNull();
  });

  it("keeps a missing object on not-found", async () => {
    getCatalogObject.mockResolvedValue({ object: null });
    const { CatalogObjectDetail } = await import(
      "@/features/sources/catalog-detail/CatalogObjectDetail"
    );
    render(shell(createElement(CatalogObjectDetail, { objectId: "obj_missing" })));

    expect(await screen.findByRole("heading", { name: "Page not found" })).toBeTruthy();
    expect(screen.queryByRole("button", { name: "Not loaded" })).toBeNull();
    expect(screen.queryByRole("alert")).toBeNull();
    expect(getCatalogObject).toHaveBeenCalledTimes(1);
  });
});
