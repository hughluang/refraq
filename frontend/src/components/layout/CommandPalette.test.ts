/** @vitest-environment jsdom */

import { MantineProvider } from "@mantine/core";
import { cleanup, fireEvent, render, screen, waitFor, act } from "@testing-library/react";
import { createElement, type ReactNode } from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import type { ModuleIdentity } from "@/features/console/module-identity/types";
import type { NavigationGroup } from "@/features/console/types";

const harness = vi.hoisted(() => {
  const copy: Record<string, string> = {
    "layout.palette.open": "Search",
    "layout.palette.recent": "Recent",
    "layout.palette.goTo": "Go to",
    "layout.palette.create": "Create",
    "layout.palette.createItem": "Create {{module}}",
    "layout.palette.records": "Records",
    "layout.palette.actions": "Actions",
    "layout.palette.action.colorScheme": "Toggle color scheme",
    "layout.palette.action.navigation": "Toggle navigation",
    "layout.palette.action.language": "Change language",
    "layout.palette.action.account": "Open Account Center",
    "layout.palette.shortcut.palette": "Command palette",
    "layout.palette.shortcut.search": "List search",
    "layout.palette.shortcut.navigation": "Navigation",
    "users.title": "Users",
    "roles.title": "Roles",
    "sources.title": "Sources",
    "colorScheme.light": "Light",
    "colorScheme.dark": "Dark",
    "colorScheme.system": "System",
    "layout.language": "Language",
    "account.profile.error": "Could not save",
  };
  function translate(key: string, options?: Record<string, unknown>) {
    const template = copy[key] ?? key;
    if (!options) return template;
    return template.replace(/\{\{(\w+)\}\}/g, (_, name: string) =>
      String(options[name] ?? ""),
    );
  }
  return {
    translate,
    push: vi.fn(),
    changeLanguage: vi.fn(async () => undefined),
    patch: vi.fn(async () => ({ id: "user_1", locale: "zh-CN" })),
    grants: new Set<string>(),
    toggleNavigation: vi.fn(),
    users: vi.fn(async () => [] as { id: string; name: string; key: string }[]),
    roles: vi.fn(async () => [] as { id: string; name: string; key: string }[]),
    sources: vi.fn(async () => [] as { id: string; name: string; key: string }[]),
    entities: vi.fn(async () => [] as { id: string; name: string; key: string }[]),
    dictionaries: vi.fn(async () => [] as { id: string; name: string; key: string }[]),
    groups: vi.fn(async () => [] as { id: string; name: string; key: string }[]),
    channels: vi.fn(async () => ({ items: [], total: 0, limit: 5, offset: 0 })),
    pending: [] as {
      query: string;
      resolve: (rows: { id: string; name: string; key: string }[]) => void;
    }[],
  };
});

vi.mock("@refinedev/core", () => ({
  useTranslate: () => harness.translate,
  useCan: ({ resource, action }: { resource: string; action: string }) => ({
    data: { can: harness.grants.has(`${resource}:${action}`) },
    isLoading: false,
  }),
  useGetIdentity: () => ({
    data: { id: "user_1", locale: "en-US" },
  }),
  useNotification: () => ({ open: vi.fn() }),
}));

vi.mock("next-i18next/client", () => ({
  useT: () => ({
    t: harness.translate,
    i18n: { language: "en-US", resolvedLanguage: "en-US" },
  }),
  useChangeLanguage: () => harness.changeLanguage,
}));

vi.mock("next/navigation", () => ({
  usePathname: () => "/console",
  useRouter: () => ({ push: harness.push, replace: vi.fn(), refresh: vi.fn() }),
  useSearchParams: () => new URLSearchParams(),
}));

vi.mock("@/features/account/api", () => ({
  patchAccountProfile: harness.patch,
}));

vi.mock("@/components/form/recordPickerAdapters", () => ({
  userRecordAdapter: () => ({ search: harness.users }),
  roleRecordAdapter: () => ({ search: harness.roles }),
  sourceRecordAdapter: () => ({ search: harness.sources }),
  entityRecordAdapter: () => ({ search: harness.entities }),
  dictionaryRecordAdapter: () => ({ search: harness.dictionaries }),
  userGroupRecordAdapter: () => ({ search: harness.groups }),
}));

vi.mock("@/features/channels/api", () => ({
  listChannels: harness.channels,
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
  Element.prototype.scrollIntoView = () => {};
}

function identity(
  id: string,
  routes: ModuleIdentity["routes"],
): ModuleIdentity {
  return {
    id,
    label_key: `${id}.title`,
    icon: id === "users" ? "users" : null,
    routes,
    actions: {
      list: `${id}:read`,
      create: `${id}:write`,
      edit: null,
      delete: null,
      show: null,
      sample: null,
    },
  };
}

const USERS = identity("users", {
  list: "/console/users",
  create: "/console/users/new",
  show: "/console/users/:id",
});
const ROLES = identity("roles", {
  list: "/console/roles",
  create: "/console/roles/new",
  edit: "/console/roles/:id",
});
const SOURCES = identity("sources", {
  list: "/console/sources",
  create: null,
  show: "/console/sources/:id/structure-diffs",
});

function shell(node: ReactNode) {
  return createElement(
    MantineProvider,
    { defaultColorScheme: "light", env: "test" },
    node,
  );
}

async function renderPalette(groups: NavigationGroup[]) {
  const { useModuleIdentityStore } = await import("@/features/console/module-identity");
  useModuleIdentityStore.setState({
    status: "ready",
    modules: [USERS, ROLES, SOURCES],
  });
  const { ConsoleNavDataProvider } = await import("@/components/layout/consoleNavData");
  const { CommandPalette } = await import("@/components/layout/CommandPalette");
  const { spotlight } = await import("@mantine/spotlight");
  render(
    shell(
      createElement(
        ConsoleNavDataProvider,
        {
          groups,
          ready: true,
          toggleNavigation: harness.toggleNavigation,
        },
        createElement(CommandPalette),
      ),
    ),
  );
  spotlight.open();
}

describe("command palette", () => {
  beforeEach(() => {
    stubDomApis();
    window.localStorage.clear();
    harness.grants.clear();
    harness.push.mockClear();
    harness.patch.mockClear();
    harness.changeLanguage.mockClear();
    harness.toggleNavigation.mockClear();
    harness.pending.length = 0;
    for (const search of [
      harness.users,
      harness.roles,
      harness.sources,
      harness.entities,
      harness.dictionaries,
      harness.groups,
    ]) {
      search.mockReset();
      search.mockResolvedValue([]);
    }
    harness.channels.mockReset();
    harness.channels.mockResolvedValue({ items: [], total: 0, limit: 5, offset: 0 });
  });

  afterEach(async () => {
    const { spotlight } = await import("@mantine/spotlight");
    spotlight.close();
    const { useModuleIdentityStore } = await import("@/features/console/module-identity");
    useModuleIdentityStore.setState({ status: "idle", modules: [] });
    cleanup();
    vi.useRealTimers();
  });

  it("offers permitted modules and create actions only", async () => {
    harness.grants.add("roles:create");
    await renderPalette([
      {
        id: "admin",
        label_key: "layout.navGroup.admin",
        modules: [
          { id: "users", label_key: "users.title", route: "/console/users" },
          { id: "sources", label_key: "sources.title", route: "/console/sources" },
        ],
      },
    ]);

    expect(await screen.findByRole("button", { name: "Users" })).toBeTruthy();
    expect(screen.getByRole("button", { name: "Sources" })).toBeTruthy();
    expect(screen.queryByRole("button", { name: "Roles" })).toBeNull();
    expect(await screen.findByRole("button", { name: "Create Roles" })).toBeTruthy();
    expect(screen.queryByRole("button", { name: "Create Users" })).toBeNull();
    expect(screen.queryByRole("button", { name: "Create Sources" })).toBeNull();
    expect(screen.getByText("Go to")).toBeTruthy();
    expect(screen.getByText("Create")).toBeTruthy();

    fireEvent.click(screen.getByRole("button", { name: "Users" }));
    await waitFor(() => {
      expect(harness.push).toHaveBeenCalledWith("/console/users");
    });
  });

  it("keeps records from modules that succeed when one module fails", async () => {
    harness.grants.add("users:list");
    harness.grants.add("roles:list");
    const rows = Array.from({ length: 6 }, (_, index) => ({
      id: `u${index + 1}`,
      name: `User ${index + 1}`,
      key: `u${index + 1}`,
    }));
    harness.users.mockResolvedValue(rows);
    harness.roles.mockRejectedValue(new Error("roles down"));
    await renderPalette([]);

    fireEvent.change(screen.getByRole("textbox", { name: "Search" }), {
      target: { value: "user" },
    });

    await waitFor(() => {
      expect(screen.getByRole("button", { name: /User 1/ })).toBeTruthy();
    });
    expect(screen.getByRole("button", { name: /User 5/ })).toBeTruthy();
    expect(screen.queryByRole("button", { name: /User 6/ })).toBeNull();
    expect(screen.queryByText("Roles")).toBeNull();
    expect(harness.roles).toHaveBeenCalled();
    expect(screen.getByText("Records")).toBeTruthy();

    fireEvent.click(screen.getByRole("button", { name: /User 1/ }));
    await waitFor(() => {
      expect(harness.push).toHaveBeenCalledWith("/console/users/u1");
    });
  });

  it("ignores a record response for an older query", async () => {
    harness.grants.add("users:list");
    harness.users.mockImplementation(
      (query: string) =>
        new Promise((resolve) => {
          harness.pending.push({ query, resolve });
        }),
    );
    await renderPalette([]);
    expect(screen.getByRole("textbox", { name: "Search" })).toBeTruthy();
    vi.useFakeTimers({ toFake: ["setTimeout", "clearTimeout"] });

    fireEvent.change(screen.getByRole("textbox", { name: "Search" }), {
      target: { value: "al" },
    });
    await act(async () => {
      vi.advanceTimersByTime(250);
    });
    fireEvent.change(screen.getByRole("textbox", { name: "Search" }), {
      target: { value: "ada" },
    });
    await act(async () => {
      vi.advanceTimersByTime(250);
    });

    const ada = harness.pending.find((item) => item.query === "ada");
    const older = harness.pending.find((item) => item.query === "al");
    expect(ada).toBeTruthy();
    expect(older).toBeTruthy();
    await act(async () => {
      ada?.resolve([{ id: "u2", name: "Ada", key: "ada" }]);
    });
    expect(screen.getByRole("button", { name: /Ada/ })).toBeTruthy();
    await act(async () => {
      older?.resolve([{ id: "u1", name: "Alan", key: "al" }]);
    });
    expect(screen.queryByRole("button", { name: /Alan/ })).toBeNull();
    expect(screen.getByRole("button", { name: /Ada/ })).toBeTruthy();
  });

  it("lists palette actions and shortcut hints", async () => {
    await renderPalette([]);
    expect(screen.getByRole("button", { name: /Toggle color scheme/ })).toBeTruthy();
    expect(screen.getByRole("button", { name: "Toggle navigation" })).toBeTruthy();
    expect(screen.getByRole("button", { name: /Change language/ })).toBeTruthy();
    expect(screen.getByRole("button", { name: "Open Account Center" })).toBeTruthy();
    expect(screen.getByText("Command palette")).toBeTruthy();
    expect(screen.getByText("List search")).toBeTruthy();
    expect(screen.getByText("Navigation")).toBeTruthy();
    expect(screen.getByText("/")).toBeTruthy();
    expect(screen.getByText("[")).toBeTruthy();

    fireEvent.click(screen.getByRole("button", { name: /Toggle color scheme/ }));
    expect(window.localStorage.getItem("mantine-color-scheme-value")).toBe("dark");

    const { spotlight } = await import("@mantine/spotlight");
    spotlight.open();
    fireEvent.click(await screen.findByRole("button", { name: "Toggle navigation" }));
    expect(harness.toggleNavigation).toHaveBeenCalledTimes(1);

    spotlight.open();
    fireEvent.click(await screen.findByRole("button", { name: "Open Account Center" }));
    await waitFor(() => {
      expect(harness.push).toHaveBeenCalledWith("/console/account");
    });

    spotlight.open();
    fireEvent.click(await screen.findByRole("button", { name: /Change language/ }));
    await waitFor(() => {
      expect(harness.patch).toHaveBeenCalledWith({ locale: "zh-CN" });
    });
    expect(harness.changeLanguage).toHaveBeenCalledWith("zh-CN");
  });
});
