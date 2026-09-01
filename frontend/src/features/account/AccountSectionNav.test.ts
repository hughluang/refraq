/** @vitest-environment jsdom */

import { MantineProvider } from "@mantine/core";
import { cleanup, render, screen } from "@testing-library/react";
import { createElement } from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { ACCOUNT_SECTION } from "@/features/account/account-sections";

const canTokens = vi.hoisted(() => ({ current: true }));

vi.mock("@refinedev/core", () => ({
  useTranslate: () => (key: string) => key,
  useCan: () => ({ data: { can: canTokens.current } }),
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
  class IntersectionObserverStub {
    observe() {}
    unobserve() {}
    disconnect() {}
  }
  globalThis.ResizeObserver = ResizeObserverStub;
  globalThis.IntersectionObserver = IntersectionObserverStub;
}

describe("AccountSectionNav", () => {
  beforeEach(() => {
    stubDomApis();
    canTokens.current = true;
    window.location.hash = "";
  });

  afterEach(() => {
    cleanup();
  });

  it("hides the tokens item without tokens:read and keeps profile and MCP", async () => {
    canTokens.current = false;
    const { AccountSectionNav } = await import(
      "@/features/account/AccountSectionNav"
    );
    render(
      createElement(MantineProvider, null, createElement(AccountSectionNav)),
    );

    expect(
      screen.getByRole("button", { name: "account.section.profile" }),
    ).not.toBeNull();
    expect(
      screen.queryByRole("button", { name: "tokens.title" }),
    ).toBeNull();
    expect(
      screen.getByRole("button", { name: "account.mcp.title" }),
    ).not.toBeNull();
    expect(screen.queryByRole("link")).toBeNull();
  });

  it("shows profile, tokens, and MCP when tokens:read is granted", async () => {
    const { AccountSectionNav } = await import(
      "@/features/account/AccountSectionNav"
    );
    render(
      createElement(MantineProvider, null, createElement(AccountSectionNav)),
    );

    expect(
      screen.getByRole("button", { name: "account.section.profile" }),
    ).not.toBeNull();
    expect(
      screen.getByRole("button", { name: "tokens.title" }),
    ).not.toBeNull();
    expect(
      screen.getByRole("button", { name: "account.mcp.title" }),
    ).not.toBeNull();
  });

  it("scrolls a section without writing a hash", async () => {
    const { AccountSectionNav } = await import(
      "@/features/account/AccountSectionNav"
    );
    const target = document.createElement("div");
    target.id = ACCOUNT_SECTION.mcp;
    const scrollIntoView = vi.fn();
    target.scrollIntoView = scrollIntoView;
    document.body.append(target);

    render(
      createElement(MantineProvider, null, createElement(AccountSectionNav)),
    );
    screen.getByRole("button", { name: "account.mcp.title" }).click();

    expect(scrollIntoView).toHaveBeenCalledWith({
      behavior: "smooth",
      block: "start",
    });
    expect(window.location.hash).toBe("");
  });

  it("scrolls the profile section without writing a hash", async () => {
    const { AccountSectionNav } = await import(
      "@/features/account/AccountSectionNav"
    );
    const target = document.createElement("div");
    target.id = ACCOUNT_SECTION.profile;
    const scrollIntoView = vi.fn();
    target.scrollIntoView = scrollIntoView;
    document.body.append(target);

    render(
      createElement(MantineProvider, null, createElement(AccountSectionNav)),
    );
    screen.getByRole("button", { name: "account.section.profile" }).click();

    expect(scrollIntoView).toHaveBeenCalledWith({
      behavior: "smooth",
      block: "start",
    });
    expect(window.location.hash).toBe("");
  });
});
