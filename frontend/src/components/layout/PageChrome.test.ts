/** @vitest-environment jsdom */

import { Button, MantineProvider } from "@mantine/core";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { createElement, useEffect, type ReactNode } from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const breadcrumbs = vi.hoisted(() => ({
  current: [] as Array<{ label: string; href?: string }>,
}));

const nav = vi.hoisted(() => ({
  params: new URLSearchParams(),
  replace: vi.fn(),
  pathname: "/console/entities/ent_1",
}));

const session = vi.hoisted(() => ({
  userId: null as string | null,
}));

vi.mock("@refinedev/core", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@refinedev/core")>();
  return {
    ...actual,
    useTranslate: () => (key: string) => key,
    useBreadcrumb: () => ({ breadcrumbs: breadcrumbs.current }),
  };
});

vi.mock("next/link", () => ({
  default: ({ href, children }: { href: string; children: ReactNode }) =>
    createElement("a", { href }, children),
  useLinkStatus: () => ({ pending: false }),
}));

vi.mock("next/navigation", () => ({
  usePathname: () => nav.pathname,
  useRouter: () => ({ push: vi.fn(), replace: nav.replace, refresh: vi.fn() }),
  useSearchParams: () => nav.params,
}));

vi.mock("@/features/branding/BrandingProvider", () => ({
  useBranding: () => ({ brandName: "Refraq" }),
}));

vi.mock("@/providers/session-store", () => ({
  useSessionStore: (
    selector: (state: { user: { id: string } | null }) => unknown,
  ) => selector({ user: session.userId ? { id: session.userId } : null }),
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

function precedes(earlier: Node, later: Node) {
  return Boolean(
    earlier.compareDocumentPosition(later) & Node.DOCUMENT_POSITION_FOLLOWING,
  );
}

function shell(node: ReactNode) {
  return createElement(MantineProvider, null, node);
}

const entitiesModule = {
  id: "entities",
  label_key: "entities.title",
  routes: {
    list: "/console/entities",
    create: "/console/entities/new",
    edit: "/console/entities/:id/edit",
    show: "/console/entities/:id",
  },
  actions: {
    list: "entity:read",
    create: "entity:write",
    edit: "entity:write",
    delete: "entity:write",
    show: "entity:read",
  },
};

async function resetModules() {
  const { useModuleIdentityStore } = await import(
    "@/features/console/module-identity/store"
  );
  useModuleIdentityStore.setState({
    status: "idle",
    modules: [],
    error: null,
    errorKind: null,
  });
}

describe("PageChrome", () => {
  beforeEach(async () => {
    stubDomApis();
    breadcrumbs.current = [];
    nav.params = new URLSearchParams();
    nav.replace.mockClear();
    nav.pathname = "/console/entities/ent_1";
    session.userId = null;
    window.localStorage.clear();
    document.title = "";
    await resetModules();
  });

  afterEach(() => {
    cleanup();
  });

  it("keeps the header fixed and scrolls only the content region", async () => {
    breadcrumbs.current = [
      { label: "entities.title", href: "/console/entities" },
      { label: "Record" },
    ];
    const { PageChrome } = await import("@/components/layout/PageChrome");
    render(
      shell(
        createElement(
          PageChrome,
          {
            title: "Record",
            description: "About this record",
            actions: createElement(Button, { size: "sm" }, "Save"),
            toolbar: createElement("div", null, "Filters"),
            tabs: createElement("div", null, "Tab list"),
          },
          "Body",
        ),
      ),
    );

    const header = document.querySelector("[data-page-header]");
    const content = document.querySelector("[data-page-scroll]");
    const crumb = screen.getByRole("navigation", { name: "layout.breadcrumb" });
    const heading = screen.getByRole("heading", { name: "Record" });
    const action = screen.getByRole("button", { name: "Save" });
    expect(header).not.toBeNull();
    expect(content).not.toBeNull();
    expect(header?.contains(heading)).toBe(true);
    expect(header?.contains(action)).toBe(true);
    expect(header?.contains(screen.getByText("About this record"))).toBe(true);
    expect(header?.contains(screen.getByText("Filters"))).toBe(true);
    expect(header?.contains(screen.getByText("Tab list"))).toBe(true);
    expect(content?.contains(screen.getByText("Body"))).toBe(true);
    expect(content?.contains(heading)).toBe(false);
    expect(content?.getAttribute("style") ?? "").toContain("overflow: auto");
    expect(header?.getAttribute("style") ?? "").not.toContain("overflow: auto");
    expect(precedes(crumb, heading)).toBe(true);
    expect(precedes(heading, action)).toBe(true);
    expect(precedes(action, screen.getByText("About this record"))).toBe(true);
    expect(heading.tagName).toBe("H1");
    expect(heading.getAttribute("data-page-heading")).toBe("");
    expect(heading.tabIndex).toBe(-1);
    expect(heading.getAttribute("style") ?? "").toContain("h2");
  });

  it("does not scroll the content region when fill is set", async () => {
    const { PageChrome } = await import("@/components/layout/PageChrome");
    render(shell(createElement(PageChrome, { title: "Users", fill: true }, "Rows")));
    const content = document.querySelector("[data-page-scroll]");
    expect(content?.getAttribute("style") ?? "").toContain("overflow: hidden");
  });

  it("omits the actions cluster when actions are absent", async () => {
    const { PageChrome } = await import("@/components/layout/PageChrome");
    render(shell(createElement(PageChrome, { title: "Record" })));
    expect(screen.queryByRole("button")).toBeNull();
  });

  it("keeps the header while the body is loading", async () => {
    const { PageChrome } = await import("@/components/layout/PageChrome");
    render(
      shell(
        createElement(PageChrome, { title: "Entities", status: "loading" }, "Secret"),
      ),
    );
    const heading = screen.getByRole("heading", { name: "Entities" });
    expect(document.querySelector("[data-page-header]")?.contains(heading)).toBe(true);
    expect(screen.queryByText("Secret")).toBeNull();
    expect(document.querySelector(".mantine-Skeleton-root")).not.toBeNull();
  });

  it("keeps the header and retries from the content region", async () => {
    const onRetry = vi.fn();
    const { PageChrome } = await import("@/components/layout/PageChrome");
    render(
      shell(
        createElement(
          PageChrome,
          {
            title: "Entities",
            status: "error",
            errorMessage: "Load failed",
            onRetry,
          },
          "Secret",
        ),
      ),
    );
    expect(screen.getByRole("heading", { name: "Entities" })).not.toBeNull();
    expect(screen.queryByText("Secret")).toBeNull();
    fireEvent.click(screen.getByRole("button", { name: "common.retry" }));
    expect(onRetry).toHaveBeenCalledOnce();
  });

  it("sets the document title from the page title, record title, and brand", async () => {
    const { PageChrome } = await import("@/components/layout/PageChrome");
    const view = render(shell(createElement(PageChrome, { title: "Users" })));
    expect(document.title).toBe("Users · Refraq");
    view.rerender(
      shell(
        createElement(PageChrome, { title: "Users", recordTitle: "Ada" }),
      ),
    );
    expect(document.title).toBe("Ada · Users · Refraq");
  });

  it("uses the module label when the title is empty and names a record from the route", async () => {
    const { useModuleIdentityStore } = await import(
      "@/features/console/module-identity/store"
    );
    useModuleIdentityStore.setState({
      status: "ready",
      modules: [entitiesModule],
      error: null,
      errorKind: null,
    });
    const { PageChrome } = await import("@/components/layout/PageChrome");
    const view = render(
      shell(createElement(PageChrome, { title: "", status: "loading" })),
    );
    expect(screen.getByRole("heading", { name: "entities.title" })).not.toBeNull();
    expect(document.title).toBe("entities.title · Refraq");
    view.rerender(shell(createElement(PageChrome, { title: "Ada" })));
    expect(document.title).toBe("Ada · entities.title · Refraq");
    nav.pathname = "/console/entities";
    view.rerender(shell(createElement(PageChrome, { title: "entities.title" })));
    expect(document.title).toBe("entities.title · Refraq");
  });

  it("records a recent visit for the current user", async () => {
    session.userId = "user_1";
    const { PageChrome } = await import("@/components/layout/PageChrome");
    const { readRecents } = await import("@/lib/recents");
    render(
      shell(
        createElement(PageChrome, {
          title: "Entities",
          recent: {
            moduleId: "entities",
            title: "Ada",
            href: "/console/entities/ent_1",
          },
        }),
      ),
    );
    expect(readRecents("user_1")).toMatchObject([
      { moduleId: "entities", title: "Ada", href: "/console/entities/ent_1" },
    ]);
    expect(typeof readRecents("user_1")[0]?.visitedAt).toBe("number");
  });

  it("stores the current query when a recent visit omits href", async () => {
    session.userId = "user_1";
    nav.params = new URLSearchParams("tab=data");
    const { PageChrome } = await import("@/components/layout/PageChrome");
    const { readRecents } = await import("@/lib/recents");
    render(
      shell(
        createElement(PageChrome, {
          title: "Entities",
          recent: { moduleId: "entities", title: "Ada" },
        }),
      ),
    );
    expect(readRecents("user_1")[0]).toMatchObject({
      moduleId: "entities",
      title: "Ada",
      href: "/console/entities/ent_1?tab=data",
    });
  });

  it("records a show route without an explicit recent and skips a list route", async () => {
    session.userId = "user_1";
    const { useModuleIdentityStore } = await import(
      "@/features/console/module-identity/store"
    );
    useModuleIdentityStore.setState({
      status: "ready",
      modules: [entitiesModule],
      error: null,
      errorKind: null,
    });
    const { PageChrome } = await import("@/components/layout/PageChrome");
    const { readRecents } = await import("@/lib/recents");
    const view = render(
      shell(createElement(PageChrome, { title: "entities.title", recordTitle: "Ada" })),
    );
    expect(readRecents("user_1")[0]).toMatchObject({
      moduleId: "entities",
      title: "Ada",
      href: "/console/entities/ent_1",
    });
    nav.pathname = "/console/entities";
    view.rerender(shell(createElement(PageChrome, { title: "entities.title" })));
    expect(readRecents("user_1")).toHaveLength(1);
  });
});

describe("PageTabs", () => {
  beforeEach(() => {
    stubDomApis();
    nav.params = new URLSearchParams("tab=missing");
    nav.replace.mockClear();
  });

  afterEach(() => {
    cleanup();
  });

  it("falls back to the first tab, replaces the query, and keeps visited panels mounted", async () => {
    const mounts = { overview: 0, attributes: 0 };
    function OverviewPanel() {
      useEffect(() => {
        mounts.overview += 1;
      }, []);
      return createElement("p", null, "Overview panel");
    }
    function AttributesPanel() {
      useEffect(() => {
        mounts.attributes += 1;
      }, []);
      return createElement("p", null, "Attributes panel");
    }
    const { PageTabs, useConsoleTab } = await import("@/components/layout/consoleTabs");
    const { PageChrome } = await import("@/components/layout/PageChrome");
    const tabs = [
      {
        value: "overview",
        label: "Overview",
        panel: createElement(OverviewPanel),
      },
      {
        value: "attributes",
        label: "Attributes",
        panel: createElement(AttributesPanel),
      },
    ];
    function Harness() {
      const tab = useConsoleTab(tabs);
      return createElement(PageTabs, {
        tabs,
        value: tab.value,
        onChange: tab.setTab,
        children: ({ list, panels }: { list: ReactNode; panels: ReactNode }) =>
          createElement(PageChrome, { title: "Entity", tabs: list }, panels),
      });
    }
    const replaceState = vi.spyOn(window.history, "replaceState");
    render(shell(createElement(Harness)));

    expect(screen.getByText("Overview panel")).not.toBeNull();
    expect(document.querySelector("[data-tab-panel='attributes']")).toBeNull();
    expect(replaceState).not.toHaveBeenCalled();

    fireEvent.click(screen.getByRole("tab", { name: "Attributes" }));
    expect(screen.getByText("Attributes panel")).not.toBeNull();
    expect(document.querySelector("[data-tab-panel='overview']")?.hasAttribute("hidden")).toBe(
      true,
    );
    expect(mounts.overview).toBe(1);
    expect(String(replaceState.mock.calls.at(-1)?.[2])).toContain("tab=attributes");
    expect(nav.replace).not.toHaveBeenCalled();

    fireEvent.click(screen.getByRole("tab", { name: "Overview" }));
    expect(mounts.overview).toBe(1);
    replaceState.mockRestore();
  });
});

describe("recents", () => {
  beforeEach(() => {
    window.localStorage.clear();
  });

  it("keeps twenty visits, shows eight in the palette, dedupes, and clears one user", async () => {
    const {
      rememberRecent,
      readRecents,
      RECENTS_PALETTE_LIMIT,
      clearRecents,
      subscribeRecents,
    } = await import("@/lib/recents");
    const listener = vi.fn();
    const unsubscribe = subscribeRecents(listener);
    for (let index = 0; index < 21; index += 1) {
      rememberRecent("user_1", {
        moduleId: "entities",
        title: `Record ${index}`,
        href: `/console/entities/${index}`,
      });
    }
    rememberRecent("user_1", {
      moduleId: "entities",
      title: "Record 3 again",
      href: "/console/entities/3",
    });
    rememberRecent("user_2", {
      moduleId: "users",
      title: "Other",
      href: "/console/users/u",
    });
    const records = readRecents("user_1");
    expect(records).toHaveLength(20);
    expect(records[0]).toMatchObject({
      title: "Record 3 again",
      href: "/console/entities/3",
    });
    expect(records.filter((record) => record.href === "/console/entities/3")).toHaveLength(1);
    expect(records.some((record) => record.href.endsWith("/0"))).toBe(false);
    expect(typeof records[0]?.visitedAt).toBe("number");
    const palette = readRecents("user_1").slice(0, RECENTS_PALETTE_LIMIT);
    expect(palette).toHaveLength(8);
    expect(palette[0]?.title).toBe("Record 3 again");
    expect(readRecents("user_2")).toHaveLength(1);
    expect(listener).toHaveBeenCalled();
    clearRecents("user_1");
    expect(readRecents("user_1")).toEqual([]);
    expect(readRecents("user_2")).toHaveLength(1);
    unsubscribe();
  });
});

describe("HeaderActions", () => {
  beforeEach(() => {
    stubDomApis();
  });

  afterEach(() => {
    cleanup();
  });

  it("does not treat raw buttons as header primaries", async () => {
    const { assertSinglePrimary } = await import("@/components/layout/HeaderActions");
    expect(() =>
      assertSinglePrimary([
        createElement(Button, { variant: "filled" }, "Run"),
        createElement(Button, null, "Save"),
      ]),
    ).not.toThrow();
  });

  it("allows one filled primary and separates clusters", async () => {
    const { assertSinglePrimary, HeaderActions } = await import(
      "@/components/layout/HeaderActions"
    );
    expect(() =>
      assertSinglePrimary([
        createElement(Button, { variant: "light" }, "Run"),
        createElement(Button, null, "Save"),
      ]),
    ).not.toThrow();
    render(
      shell(
        createElement(HeaderActions, {
          navigation: createElement(Button, { variant: "subtle", size: "sm" }, "Back"),
          lifecycle: null,
          standard: createElement(Button, { size: "sm" }, "Save"),
        }),
      ),
    );
    expect(screen.getByRole("separator")).not.toBeNull();
    expect(screen.getByRole("button", { name: "Back" })).not.toBeNull();
    expect(screen.getByRole("button", { name: "Save" })).not.toBeNull();
  });

  it("treats a typed primary as the only filled action", async () => {
    const { assertSinglePrimary, HeaderAction } = await import(
      "@/components/layout/HeaderActions"
    );
    const save = createElement(
      HeaderAction,
      { primary: true },
      createElement(Button, { variant: "light" }, "Save"),
    );
    const run = createElement(Button, { variant: "light" }, "Run");
    expect(() => assertSinglePrimary([save, run])).not.toThrow();
    expect(() =>
      assertSinglePrimary([
        save,
        createElement(HeaderAction, { primary: true }, createElement(Button, null, "Publish")),
      ]),
    ).toThrow(/filled primary/);
  });
});

describe("SectionHeader embedded actions", () => {
  beforeEach(() => {
    stubDomApis();
  });

  afterEach(() => {
    cleanup();
  });

  it("keeps actions beside a lower heading", async () => {
    const { SectionHeader } = await import("@/components/layout/SectionHeader");
    render(
      shell(
        createElement(SectionHeader, {
          title: "Tokens",
          order: 4,
          actions: createElement(Button, { size: "sm" }, "Create"),
        }),
      ),
    );

    const heading = screen.getByRole("heading", { name: "Tokens" });
    const action = screen.getByRole("button", { name: "Create" });
    expect(heading.tagName).toBe("H4");
    expect(heading.hasAttribute("data-page-heading")).toBe(false);
    expect(precedes(heading, action)).toBe(true);
  });
});
