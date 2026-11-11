/** @vitest-environment jsdom */

import { MantineProvider } from "@mantine/core";
import { cleanup, render, screen } from "@testing-library/react";
import { createElement, type ReactNode } from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { McpWorkspaceProvider } from "@/features/mcp/McpWorkspaceProvider";
import en from "@/locales/en-US/common.json";

const copy = en as Record<string, string>;

const api = vi.hoisted(() => vi.fn());
const pathname = vi.hoisted(() => ({ current: "/console/mcp" }));

vi.mock("@/lib/api", async () => {
  const actual = await vi.importActual<typeof import("@/lib/api")>("@/lib/api");
  return {
    ...actual,
    apiClient: (...args: unknown[]) => api(...args),
  };
});

vi.mock("@refinedev/core", () => ({
  useTranslate: () => (key: string) => copy[key] ?? key,
  useNotification: () => ({ open: vi.fn() }),
  useBreadcrumb: () => ({ breadcrumbs: [] }),
  useGetIdentity: () => ({ data: undefined }),
}));

vi.mock("next/link", () => ({
  default: ({ href, children }: { href: string; children?: ReactNode }) =>
    createElement("a", { href }, children),
  useLinkStatus: () => ({ pending: false }),
}));

vi.mock("next/navigation", () => ({
  usePathname: () => pathname.current,
  useRouter: () => ({ push: vi.fn(), replace: vi.fn(), refresh: vi.fn() }),
  useSearchParams: () => new URLSearchParams(),
}));

vi.mock("@/features/branding/BrandingProvider", () => ({
  useBranding: () => ({ brandName: "Refraq" }),
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

function shell(node: ReactNode) {
  return createElement(
    MantineProvider,
    { env: "test" },
    createElement(McpWorkspaceProvider, null, node),
  );
}

function expectNoCatalogOrClientConfig(options?: { detail?: boolean }) {
  if (!options?.detail) {
    expect(api).not.toHaveBeenCalled();
  }
  expect(screen.queryByRole("table")).toBeNull();
  if (!options?.detail) {
    expect(screen.queryByRole("button", { name: /copy/i })).toBeNull();
  }
    const secretOrLegacy = options?.detail
    ? /mcpServers/i
    : /mcpServers|YOUR_TOKEN|personal access token/i;
  expect(screen.queryByText(secretOrLegacy)).toBeNull();
}

describe("MCP workspace", () => {
  beforeEach(() => {
    stubDomApis();
    api.mockReset();
    api.mockResolvedValue(undefined);
    pathname.current = "/console/mcp";
  });

  afterEach(() => {
    cleanup();
  });

  it("distinguishes Metadata MCP from Entity MCP and links to both detail routes", async () => {
    const { McpOverview } = await import("@/features/mcp/McpOverview");
    render(shell(createElement(McpOverview)));

    expect(
      screen.getByText(
        "Metadata MCP (/mcp) is Source-scoped reads and mutations.",
      ),
    ).toBeTruthy();
    expect(
      screen.getByText("Entity MCP (/mcp/entity) is read-only entity data."),
    ).toBeTruthy();
    expect(
      screen.getByRole("link", { name: "Open Metadata MCP" }),
    ).toHaveProperty("getAttribute");
    expect(
      screen.getByRole("link", { name: "Open Metadata MCP" }).getAttribute("href"),
    ).toBe("/console/mcp/metadata");
    expect(
      screen.getByRole("link", { name: "Open Entity MCP" }).getAttribute("href"),
    ).toBe("/console/mcp/entity");
    expectNoCatalogOrClientConfig();
  });

  it("identifies the Metadata endpoint and links back to the overview", async () => {
    pathname.current = "/console/mcp/metadata";
    const { McpMetadataDetail } = await import(
      "@/features/mcp/McpMetadataDetail"
    );
    render(shell(createElement(McpMetadataDetail)));

    expect(
      screen.getByRole("heading", { name: "Metadata MCP", level: 1 }),
    ).toBeTruthy();
    expect(
      screen.queryByText("This page is Entity MCP. Endpoint /mcp/entity."),
    ).toBeNull();
    expect(screen.getByRole("link", { name: "Back to MCP" }).getAttribute("href")).toBe(
      "/console/mcp",
    );
    expectNoCatalogOrClientConfig({ detail: true });
  });

  it("identifies the Entity endpoint and links back to the overview", async () => {
    pathname.current = "/console/mcp/entity";
    const { McpEntityDetail } = await import("@/features/mcp/McpEntityDetail");
    render(shell(createElement(McpEntityDetail)));

    expect(
      screen.getByRole("heading", { name: "Entity MCP", level: 1 }),
    ).toBeTruthy();
    expect(
      screen.queryByText("This page is Metadata MCP. Endpoint /mcp."),
    ).toBeNull();
    expect(screen.getByRole("link", { name: "Back to MCP" }).getAttribute("href")).toBe(
      "/console/mcp",
    );
    expectNoCatalogOrClientConfig({ detail: true });
  });
});
