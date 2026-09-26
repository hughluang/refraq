/** @vitest-environment jsdom */

import { Button, MantineProvider } from "@mantine/core";
import { cleanup, render, screen } from "@testing-library/react";
import { createElement, type ReactNode } from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const breadcrumbs = vi.hoisted(() => ({
  current: [] as Array<{ label: string; href?: string }>,
}));

vi.mock("@refinedev/core", () => ({
  useTranslate: () => (key: string) => key,
  useBreadcrumb: () => ({ breadcrumbs: breadcrumbs.current }),
}));

vi.mock("next/link", () => ({
  default: ({ href, children }: { href: string; children: ReactNode }) =>
    createElement("a", { href }, children),
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

describe("PageChrome", () => {
  beforeEach(() => {
    stubDomApis();
    breadcrumbs.current = [];
  });

  afterEach(() => {
    cleanup();
  });

  it("places page actions above the title", async () => {
    const { PageChrome } = await import("@/components/layout/PageChrome");
    render(
      createElement(
        MantineProvider,
        null,
        createElement(
          PageChrome,
          {
            title: "Record",
            actions: createElement(Button, { size: "sm" }, "Save"),
          },
        ),
      ),
    );

    const action = screen.getByRole("button", { name: "Save" });
    const heading = screen.getByRole("heading", { name: "Record" });
    expect(precedes(action, heading)).toBe(true);
  });

  it("omits the actions row when actions are absent", async () => {
    const { PageChrome } = await import("@/components/layout/PageChrome");
    render(
      createElement(
        MantineProvider,
        null,
        createElement(PageChrome, { title: "Record" }),
      ),
    );

    expect(screen.getByRole("heading", { name: "Record" })).not.toBeNull();
    expect(screen.queryByRole("button")).toBeNull();
  });

  it("keeps breadcrumb then actions then title", async () => {
    breadcrumbs.current = [
      { label: "entities.title", href: "/console/entities" },
      { label: "Record" },
    ];
    const { PageChrome } = await import("@/components/layout/PageChrome");
    render(
      createElement(
        MantineProvider,
        null,
        createElement(
          PageChrome,
          {
            title: "Record",
            actions: createElement(Button, { size: "sm" }, "Save"),
          },
        ),
      ),
    );

    const crumb = screen.getByRole("navigation", {
      name: "layout.breadcrumb",
    });
    const action = screen.getByRole("button", { name: "Save" });
    const heading = screen.getByRole("heading", { name: "Record" });
    expect(precedes(crumb, action)).toBe(true);
    expect(precedes(action, heading)).toBe(true);
  });
});

describe("SectionHeader embedded actions", () => {
  beforeEach(() => {
    stubDomApis();
  });

  afterEach(() => {
    cleanup();
  });

  it("keeps actions beside the title", async () => {
    const { SectionHeader } = await import(
      "@/components/layout/SectionHeader"
    );
    render(
      createElement(
        MantineProvider,
        null,
        createElement(SectionHeader, {
          title: "Tokens",
          order: 4,
          actions: createElement(Button, { size: "sm" }, "Create"),
        }),
      ),
    );

    const heading = screen.getByRole("heading", { name: "Tokens" });
    const action = screen.getByRole("button", { name: "Create" });
    expect(precedes(heading, action)).toBe(true);
  });
});
