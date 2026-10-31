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
  return { ...actual, getCatalogObject };
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
