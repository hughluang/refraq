/** @vitest-environment jsdom */

import { MantineProvider } from "@mantine/core";
import { notifications, notificationsStore } from "@mantine/notifications";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { createElement, type ReactNode } from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { ConsoleNotifications } from "@/providers/notification-provider";

const api = vi.hoisted(() => vi.fn());
const identity = vi.hoisted(() => ({
  id: "usr_1",
  account: "ada",
  display_name: "Ada",
  email: "ada@example.com",
  locale: "en-US",
  display_timezone: null as string | null,
  role_id: null as string | null,
  role_key: null as string | null,
  role_name: "Admin",
  permissions: [] as string[],
  identity_source: "oidc" as const,
}));

vi.mock("@/lib/api", async () => {
  const actual = await vi.importActual<typeof import("@/lib/api")>("@/lib/api");
  return {
    ...actual,
    apiClient: (...args: unknown[]) => api(...args),
  };
});

vi.mock("@refinedev/core", () => ({
  matchResourceFromRoute: () => ({ found: false }),
  useTranslate: () => (key: string) => key,
  useGetIdentity: () => ({ data: identity }),
  useNotification: () => ({ open: vi.fn() }),
  useBreadcrumb: () => ({ breadcrumbs: [] }),
  CanAccess: ({ children }: { children?: ReactNode }) => children ?? null,
}));

vi.mock("next-i18next/client", () => ({
  useChangeLanguage: () => vi.fn(),
}));

vi.mock("next/link", () => ({
  default: ({ href, children }: { href: string; children?: ReactNode }) =>
    createElement("a", { href }, children),
  useLinkStatus: () => ({ pending: false }),
}));

vi.mock("next/navigation", () => ({
  usePathname: () => "/console/account",
  useRouter: () => ({ push: vi.fn(), replace: vi.fn(), refresh: vi.fn() }),
  useSearchParams: () => new URLSearchParams(),
}));

vi.mock("@/features/branding/BrandingProvider", () => ({
  useBranding: () => ({ brandName: "Refraq" }),
}));

vi.mock("@/features/tokens/TokenList", () => ({
  TokenList: () => createElement("div", null, "tokens-section"),
}));

vi.mock("@/features/account/AccountSectionNav", () => ({
  AccountSectionNav: () => null,
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

function shell(node: ReactNode) {
  return createElement(
    MantineProvider,
    { env: "test" },
    createElement(ConsoleNotifications),
    node,
  );
}

describe("AccountPanel failures", () => {
  beforeEach(() => {
    stubDomApis();
    api.mockReset();
    resetNotifications();
    vi.resetModules();
  });

  afterEach(() => {
    cleanup();
    resetNotifications();
  });

  it("keeps the header and retries a time-zone failure from one notification", async () => {
    const { ApiError } = await import("@/lib/api");
    let zoneCalls = 0;
    api.mockImplementation((path: string) => {
      if (path === "/time-zones") {
        zoneCalls += 1;
        if (zoneCalls === 1) {
          return Promise.reject(
            new ApiError(500, "NO_SUCH_CODE", "Raw English detail", "req-zones"),
          );
        }
        return Promise.resolve({ items: [{ id: "UTC", aliases: [] }] });
      }
      return Promise.reject(new Error(`unexpected ${path}`));
    });
    const { AccountPanel } = await import("@/features/account/AccountPanel");
    render(shell(createElement(AccountPanel)));

    const heading = await screen.findByRole("heading", { name: "account.title" });
    expect(document.querySelector("[data-page-header]")?.contains(heading)).toBe(true);
    const status = await screen.findByRole("button", { name: "status.unloaded" });
    const scroll = document.querySelector("[data-page-scroll]");
    expect(scroll?.contains(status)).toBe(true);
    expect(scroll?.querySelector("[role='alert']")).toBeNull();
    expect(scroll?.textContent).not.toContain("req-zones");
    expect(screen.queryByText("common.error")).toBeNull();
    const alerts = screen.getAllByRole("alert");
    expect(alerts).toHaveLength(1);
    expect(alerts[0].textContent).toContain("problems.unknown");
    expect(alerts[0].textContent).toContain("common.requestId");
    expect(alerts[0].textContent).toContain("req-zones");

    fireEvent.click(screen.getByRole("button", { name: "common.retry" }));
    expect(await screen.findByDisplayValue("Ada")).toBeTruthy();
    expect(screen.queryByRole("button", { name: "status.unloaded" })).toBeNull();
    expect(zoneCalls).toBe(2);
  });

  it("shows one error notification and no form alert when the profile save is rejected", async () => {
    const { ApiError } = await import("@/lib/api");
    api.mockImplementation((path: string) => {
      if (path === "/time-zones") {
        return Promise.resolve({ items: [{ id: "UTC", aliases: [] }] });
      }
      if (path === "/account/profile") {
        return Promise.reject(
          new ApiError(500, "NO_SUCH_CODE", "Raw English detail", "req-profile"),
        );
      }
      return Promise.reject(new Error(`unexpected ${path}`));
    });
    const { AccountPanel } = await import("@/features/account/AccountPanel");
    render(shell(createElement(AccountPanel)));
    expect(await screen.findByDisplayValue("Ada")).toBeTruthy();
    fireEvent.submit(document.getElementById("account-profile-form") as HTMLFormElement);

    const alerts = await screen.findAllByRole("alert");
    expect(alerts).toHaveLength(1);
    const form = document.getElementById("account-profile-form");
    expect(form?.querySelector("[role='alert']")).toBeNull();
    expect(alerts[0].textContent).toContain("problems.unknown");
    expect(alerts[0].textContent).toContain("common.requestId");
    expect(alerts[0].textContent).toContain("req-profile");
    expect(screen.queryByRole("button", { name: "common.retry" })).toBeNull();
  });

  it("links to the MCP workspace and does not load endpoint catalogs", async () => {
    api.mockImplementation((path: string) => {
      if (path === "/time-zones") {
        return Promise.resolve({ items: [{ id: "UTC", aliases: [] }] });
      }
      return Promise.reject(new Error(`unexpected ${path}`));
    });
    const { AccountPanel } = await import("@/features/account/AccountPanel");
    render(shell(createElement(AccountPanel)));

    expect(await screen.findByText("tokens-section")).toBeTruthy();
    expect(
      screen.getByRole("link", { name: "account.openMcp" }).getAttribute("href"),
    ).toBe("/console/mcp");
    expect(document.getElementById("account-mcp")).toBeNull();
    expect(screen.queryByRole("table")).toBeNull();
    expect(screen.queryByRole("button", { name: /copy/i })).toBeNull();
    const paths = api.mock.calls.map((call) => call[0]);
    expect(paths).not.toContain("/mcp/catalog");
    expect(paths).not.toContain("/mcp/entity/catalog");
  });
});
