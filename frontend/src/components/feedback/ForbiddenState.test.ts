/** @vitest-environment jsdom */

import { MantineProvider } from "@mantine/core";
import { cleanup, render, screen } from "@testing-library/react";
import { createElement, type ReactNode } from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import type { ModuleIdentity } from "@/features/console/module-identity/types";

const nav = vi.hoisted(() => ({ pathname: "/console/users" }));

const copy: Record<string, string> = {
  "forbidden.description": "Your account does not have permission to access this resource",
  "forbidden.module": "You do not have access to {{module}}.",
  "forbidden.back": "Back to home",
  "users.title": "Users",
  "entities.title": "Entities",
  "dictionaries.title": "Dictionaries",
};

function translate(key: string, options?: Record<string, unknown>) {
  const template = copy[key] ?? key;
  if (!options) return template;
  return template.replace(/\{\{(\w+)\}\}/g, (_, name: string) =>
    String(options[name] ?? ""),
  );
}

vi.mock("@refinedev/core", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@refinedev/core")>();
  return {
    ...actual,
    useTranslate: () => translate,
  };
});

vi.mock("next/link", () => ({
  useLinkStatus: () => ({ pending: false }),
  default: ({
    href,
    children,
  }: {
    href: string;
    children: ReactNode;
  }) => createElement("a", { href }, children),
}));

vi.mock("next/navigation", () => ({
  usePathname: () => nav.pathname,
  useRouter: () => ({ push: vi.fn(), replace: vi.fn(), refresh: vi.fn() }),
  useSearchParams: () => new URLSearchParams(),
}));

function module(
  id: string,
  labelKey: string,
  listPermission: string,
  show: string,
): ModuleIdentity {
  return {
    id,
    label_key: labelKey,
    icon: null,
    routes: { list: `/console/${id}`, create: null, edit: null, show },
    actions: {
      list: listPermission,
      create: null,
      edit: null,
      delete: null,
      show: listPermission,
      sample: null,
    },
  };
}

function shell(node: ReactNode) {
  return createElement(MantineProvider, { env: "test" }, node);
}

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
}

describe("ForbiddenState", () => {
  beforeEach(() => {
    stubDomApis();
    nav.pathname = "/console/users";
  });

  afterEach(async () => {
    const { useModuleIdentityStore } = await import("@/features/console/module-identity");
    useModuleIdentityStore.setState({ status: "idle", modules: [] });
    cleanup();
  });

  it("names the console module and does not print the permission key", async () => {
    const { useModuleIdentityStore } = await import("@/features/console/module-identity");
    useModuleIdentityStore.setState({
      status: "ready",
      modules: [
        module("users", "users.title", "users:read", "/console/users/:id"),
        module("user-groups", "userGroups.title", "users:read", "/console/user-groups/:id"),
      ],
    });
    const { ForbiddenState } = await import("@/components/feedback/ForbiddenState");
    render(shell(createElement(ForbiddenState, { reason: "users:read" })));

    expect(screen.getByText("You do not have access to Users.")).toBeTruthy();
    expect(screen.queryByText(/users:read/)).toBeNull();
    expect(screen.queryByText("userGroups.title")).toBeNull();
    expect(screen.getByRole("link", { name: "Back to home" }).getAttribute("href")).toBe(
      "/console",
    );
  });

  it("uses the module for the current route when several share the permission", async () => {
    nav.pathname = "/console/dictionaries/dict_1";
    const { useModuleIdentityStore } = await import("@/features/console/module-identity");
    useModuleIdentityStore.setState({
      status: "ready",
      modules: [
        module("entities", "entities.title", "entity:read", "/console/entities/:id"),
        module("dictionaries", "dictionaries.title", "entity:read", "/console/dictionaries/:id"),
      ],
    });
    const { ForbiddenState } = await import("@/components/feedback/ForbiddenState");
    render(shell(createElement(ForbiddenState, { reason: "entity:read" })));

    expect(screen.getByText("You do not have access to Dictionaries.")).toBeTruthy();
    expect(screen.queryByText(/entity:read/)).toBeNull();
    expect(screen.queryByText("Entities")).toBeNull();
  });
});
