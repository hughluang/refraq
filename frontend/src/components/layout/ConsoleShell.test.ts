/** @vitest-environment jsdom */

import { MantineProvider } from "@mantine/core";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { createElement, type ReactNode } from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import type { NavigationGroup } from "@/features/console/types";

vi.mock("@refinedev/core", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@refinedev/core")>();
  const copy: Record<string, string> = {
    "forbidden.title": "Forbidden",
    "forbidden.description": "No permission",
    "forbidden.module": "You do not have access to {{module}}.",
    "forbidden.back": "Back to home",
    "users.title": "Users",
    "layout.notFound.title": "Page not found",
    "layout.notFound.description": "Missing",
    "layout.notFound.home": "Go to console home",
    "layout.skipToContent": "Skip to content",
    "layout.navGroup.workbench": "Workbench",
    "layout.navGroup.admin": "Administration",
  };
  return {
    ...actual,
    useTranslate: () => (key: string, options?: Record<string, unknown>) => {
      const template = copy[key] ?? key;
      if (!options) return template;
      return template.replace(/\{\{(\w+)\}\}/g, (_, name: string) =>
        String(options[name] ?? ""),
      );
    },
  };
});

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
    onClick?: () => void;
  }) => createElement("a", { href, ...props }, children),
}));

vi.mock("next/navigation", () => ({
  usePathname: () => "/console/users",
  useRouter: () => ({ push: vi.fn(), replace: vi.fn(), refresh: vi.fn() }),
  useSearchParams: () => new URLSearchParams(),
}));

const GROUPS: NavigationGroup[] = [
  {
    id: "workbench",
    label_key: "layout.navGroup.workbench",
    modules: [{ id: "dashboard", label_key: "Home", route: "/console" }],
  },
  {
    id: "admin",
    label_key: "layout.navGroup.admin",
    modules: [{ id: "users", label_key: "Users", route: "/console/users" }],
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
  return createElement(MantineProvider, null, node);
}

describe("console shell navigation", () => {
  beforeEach(() => {
    stubDomApis();
    window.localStorage.clear();
  });

  afterEach(() => {
    cleanup();
  });

  it("marks the longest list-route prefix as the current page", async () => {
    const { ConsoleSideNav } = await import("@/components/layout/ConsoleSideNav");
    render(
      shell(
        createElement(ConsoleSideNav, {
          groups: GROUPS,
          pathname: "/console/users/user_1",
          rail: false,
          iconFor: () => "users",
        }),
      ),
    );

    expect(screen.getByRole("link", { name: "Users" }).getAttribute("aria-current")).toBe(
      "page",
    );
    expect(screen.getByRole("link", { name: "Home" }).getAttribute("aria-current")).toBeNull();
    expect(screen.getByText("Administration")).not.toBeNull();
  });

  it("uses dividers instead of group labels in the rail", async () => {
    const { ConsoleSideNav } = await import("@/components/layout/ConsoleSideNav");
    render(
      shell(
        createElement(ConsoleSideNav, {
          groups: GROUPS,
          pathname: "/console",
          rail: true,
          iconFor: () => null,
        }),
      ),
    );

    expect(screen.queryByText("Workbench")).toBeNull();
    expect(screen.queryByText("Administration")).toBeNull();
    expect(document.querySelector("hr, [role='separator']")).not.toBeNull();
  });

  it("remembers the rail width in this browser", async () => {
    const { NAV_MODE_KEY } = await import("@/components/layout/consoleNav");
    const { useNavMode } = await import("@/components/layout/useConsoleChrome");
    window.localStorage.setItem(NAV_MODE_KEY, "rail");

    function Probe() {
      const { rail, toggle } = useNavMode();
      return createElement(
        "button",
        { type: "button", "data-rail": rail ? "true" : "false", onClick: toggle },
        rail ? "rail" : "expanded",
      );
    }

    const view = render(shell(createElement(Probe)));
    await waitFor(() => {
      expect(screen.getByRole("button").getAttribute("data-rail")).toBe("true");
    });
    fireEvent.click(screen.getByRole("button"));
    expect(window.localStorage.getItem(NAV_MODE_KEY)).toBe("expanded");
    view.unmount();

    render(shell(createElement(Probe)));
    await waitFor(() => {
      expect(screen.getByRole("button").getAttribute("data-rail")).toBe("false");
    });
  });

  it("ignores the navigation shortcut in fields and on the channel canvas", async () => {
    const { NAV_MODE_KEY } = await import("@/components/layout/consoleNav");
    const { useNavMode } = await import("@/components/layout/useConsoleChrome");

    function Probe() {
      const { rail } = useNavMode();
      return createElement("div", { "data-rail": rail ? "rail" : "expanded" });
    }

    render(shell(createElement(Probe)));
    await waitFor(() => {
      expect(document.querySelector("[data-rail]")?.getAttribute("data-rail")).toBe("expanded");
    });

    const input = document.createElement("input");
    document.body.append(input);
    input.focus();
    fireEvent.keyDown(input, { key: "[" });
    expect(window.localStorage.getItem(NAV_MODE_KEY)).not.toBe("rail");

    const canvas = document.createElement("div");
    canvas.className = "react-flow";
    const node = document.createElement("button");
    node.type = "button";
    canvas.append(node);
    document.body.append(canvas);
    node.focus();
    fireEvent.keyDown(node, { key: "[" });
    expect(window.localStorage.getItem(NAV_MODE_KEY)).not.toBe("rail");
    node.blur();

    fireEvent.keyDown(document.body, { key: "[" });
    expect(window.localStorage.getItem(NAV_MODE_KEY)).toBe("rail");
  });

  it("closes the navigation overlay when the pathname changes", async () => {
    const { useNavOverlay } = await import("@/components/layout/useConsoleChrome");

    function Probe({ pathname }: { pathname: string }) {
      const overlay = useNavOverlay(pathname);
      return createElement(
        "div",
        null,
        createElement("button", { ref: overlay.menuRef, type: "button" }, "Menu"),
        createElement("button", { type: "button", onClick: overlay.toggle }, "Open"),
        overlay.opened
          ? createElement("div", { "data-testid": "overlay" }, "Nav")
          : null,
      );
    }

    const view = render(shell(createElement(Probe, { pathname: "/console/users" })));
    fireEvent.click(screen.getByRole("button", { name: "Open" }));
    expect(screen.getByTestId("overlay")).not.toBeNull();
    view.rerender(shell(createElement(Probe, { pathname: "/console/roles" })));
    await waitFor(() => {
      expect(screen.queryByTestId("overlay")).toBeNull();
    });

    fireEvent.click(screen.getByRole("button", { name: "Open" }));
    fireEvent.keyDown(window, { key: "Escape" });
    await waitFor(() => {
      expect(screen.queryByTestId("overlay")).toBeNull();
    });
    expect(document.activeElement).toBe(screen.getByRole("button", { name: "Menu" }));
  });

  it("points skip to content at the console main region", async () => {
    const { CONSOLE_MAIN_ID } = await import("@/components/layout/consoleNav");
    const { ConsoleSkipLink } = await import("@/components/layout/ConsoleSkipLink");
    render(
      shell(
        createElement(
          "div",
          null,
          createElement(ConsoleSkipLink),
          createElement("main", { id: CONSOLE_MAIN_ID, tabIndex: -1 }),
        ),
      ),
    );
    expect(screen.getByRole("link", { name: "Skip to content" }).getAttribute("href")).toBe(
      `#${CONSOLE_MAIN_ID}`,
    );
    expect(document.getElementById(CONSOLE_MAIN_ID)?.tabIndex).toBe(-1);
  });
});

describe("not-found and forbidden", () => {
  beforeEach(() => {
    stubDomApis();
  });

  afterEach(() => {
    cleanup();
  });

  it("uses different copy for a missing page and a permission refusal", async () => {
    const { NotFoundState } = await import("@/components/feedback/NotFoundState");
    const { ForbiddenState } = await import("@/components/feedback/ForbiddenState");
    const view = render(shell(createElement(NotFoundState)));
    expect(screen.getByRole("heading", { name: "Page not found" })).not.toBeNull();
    expect(screen.getByRole("link", { name: "Go to console home" }).getAttribute("href")).toBe(
      "/console",
    );
    view.unmount();
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
            edit: null,
            show: "/console/users/:id",
          },
          actions: {
            list: "users:read",
            create: "users:write",
            edit: "users:write",
            delete: "users:write",
            show: "users:read",
            sample: null,
          },
        },
      ],
    });
    render(shell(createElement(ForbiddenState, { reason: "users:read" })));
    expect(screen.getByText("You do not have access to Users.")).not.toBeNull();
    expect(screen.queryByText(/users:read/)).toBeNull();
    expect(screen.queryByRole("heading", { name: "Page not found" })).toBeNull();
    expect(screen.getByRole("link", { name: "Back to home" }).getAttribute("href")).toBe(
      "/console",
    );
  });
});
