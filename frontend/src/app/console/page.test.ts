/** @vitest-environment jsdom */

import { MantineProvider } from "@mantine/core";
import { cleanup, render, screen } from "@testing-library/react";
import { createElement, type ReactNode } from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import type { NavigationGroup } from "@/features/console/types";
import { rememberRecent, clearRecents } from "@/lib/recents";
import {
  resetSessionStoreForTests,
  useSessionStore,
  type CurrentUser,
} from "@/providers/session-store";

const copy: Record<string, string> = {
  "dashboard.description": "Management console home",
  "home.recents": "Recent records",
  "home.modules": "Modules",
  "users.title": "Users",
  "layout.navGroup.admin": "Administration",
  "layout.breadcrumb": "Breadcrumb",
};

vi.mock("@refinedev/core", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@refinedev/core")>();
  return {
    ...actual,
    useTranslate: () => (key: string) => copy[key] ?? key,
    useBreadcrumb: () => ({ breadcrumbs: [] }),
  };
});

vi.mock("@/features/branding/BrandingProvider", () => ({
  useBranding: () => ({ brandName: "Refraq" }),
  useBranding: () => ({ brandName: "Refraq" }),
}));

vi.mock("next/link", () => ({
  useLinkStatus: () => ({ pending: false }),
  default: ({
    href,
    children,
    onNavigate: _onNavigate,
    ...props
  }: {
    href: string;
    children: ReactNode;
    onNavigate?: () => void;
  }) => createElement("a", { href, ...props }, children),
}));

vi.mock("next/navigation", () => ({
  usePathname: () => "/console",
  useRouter: () => ({ push: vi.fn(), replace: vi.fn(), refresh: vi.fn() }),
  useSearchParams: () => new URLSearchParams(),
}));

const USER: CurrentUser = {
  id: "user_1",
  account: "ada",
  display_name: "Ada",
  email: null,
  locale: "en-US",
  display_timezone: null,
  role_id: null,
  role_key: null,
  role_name: null,
  permissions: ["users:read"],
  identity_source: "local",
};

const GROUPS: NavigationGroup[] = [
  {
    id: "admin",
    label_key: "layout.navGroup.admin",
    modules: [{ id: "users", label_key: "users.title", route: "/console/users" }],
  },
];

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

function shell(node: ReactNode) {
  return createElement(MantineProvider, { env: "test" }, node);
}

async function renderHome() {
  const { useModuleIdentityStore } = await import("@/features/console/module-identity");
  useModuleIdentityStore.setState({
    status: "ready",
    modules: [
      {
        id: "users",
        label_key: "users.title",
        icon: "users",
        routes: {
          list: "/console/users",
          create: "/console/users/new",
          show: "/console/users/:id",
        },
        actions: {
          list: "users:read",
          create: "users:write",
          edit: null,
          delete: null,
          show: "users:read",
          sample: null,
        },
      },
    ],
  });
  const { ConsoleNavDataProvider } = await import("@/components/layout/consoleNavData");
  const { default: ConsoleHomePage } = await import("@/app/console/page");
  render(
    shell(
      createElement(
        ConsoleNavDataProvider,
        { groups: GROUPS, ready: true, toggleNavigation: () => {} },
        createElement(ConsoleHomePage),
      ),
    ),
  );
}

describe("console home", () => {
  beforeEach(() => {
    stubDomApis();
    window.localStorage.clear();
    resetSessionStoreForTests();
    useSessionStore.setState({ user: USER, permissionsReady: true });
    clearRecents(USER.id);
  });

  afterEach(() => {
    clearRecents(USER.id);
    resetSessionStoreForTests();
    cleanup();
  });

  it("shows recent records and module entry points", async () => {
    rememberRecent(USER.id, {
      moduleId: "users",
      title: "Ada Lovelace",
      href: "/console/users/user_1",
    });
    await renderHome();

    expect(screen.getAllByRole("heading", { level: 1 })).toHaveLength(1);
    expect(screen.getByRole("heading", { name: "Refraq" })).toBeTruthy();
    expect(screen.getByRole("heading", { name: "Recent records" })).toBeTruthy();
    const recent = screen.getByRole("link", { name: /Ada Lovelace/ });
    expect(recent.getAttribute("href")).toBe("/console/users/user_1");
    expect(recent.textContent).toContain("Users");
    const entry = screen.getByRole("link", { name: "Users" });
    expect(entry.getAttribute("href")).toBe("/console/users");
    expect(screen.getByText("Administration")).toBeTruthy();
  });

  it("shows entry points only when there are no recents", async () => {
    await renderHome();

    expect(screen.getAllByRole("heading", { level: 1 })).toHaveLength(1);
    expect(screen.queryByRole("heading", { name: "Recent records" })).toBeNull();
    expect(screen.queryByRole("link", { name: /Ada Lovelace/ })).toBeNull();
    expect(screen.getByRole("link", { name: "Users" }).getAttribute("href")).toBe(
      "/console/users",
    );
    expect(screen.getByRole("heading", { name: "Modules" })).toBeTruthy();
  });
});
