/**
 * @vitest-environment jsdom
 * @vitest-environment-options {"url": "https://console.example.com/console/mcp/metadata"}
 */

import { MantineProvider } from "@mantine/core";
import { cleanup, render, screen } from "@testing-library/react";
import { createElement, type ReactNode } from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { McpWorkspaceProvider } from "@/features/mcp/McpWorkspaceProvider";
import en from "@/locales/en-US/common.json";

const copy = en as Record<string, string>;

const api = vi.hoisted(() => vi.fn());
const pathname = vi.hoisted(() => ({ current: "/console/mcp/metadata" }));

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

describe("MCP endpoint connection guidance", () => {
  beforeEach(() => {
    stubDomApis();
    api.mockReset();
    api.mockResolvedValue(undefined);
    pathname.current = "/console/mcp/metadata";
  });

  afterEach(() => {
    cleanup();
  });

  it("explains Metadata purpose, writes, and Source-scoped access", async () => {
    const { McpMetadataDetail } = await import("@/features/mcp/McpMetadataDetail");
    render(shell(createElement(McpMetadataDetail)));

    expect(
      screen.getByText(
        "Metadata MCP is the Source-scoped face for catalog inquiry and living-registry changes.",
      ),
    ).toBeTruthy();
    expect(
      screen.getByText(
        "Authorization follows the caller's Source level. Controlled Source SQL is a read, and mutations exist.",
      ),
    ).toBeTruthy();
    expect(
      screen.getByText("A visible tool is not access to every Source."),
    ).toBeTruthy();
  });

  it("explains Entity read-only access, grants, and Profile Views", async () => {
    pathname.current = "/console/mcp/entity";
    const { McpEntityDetail } = await import("@/features/mcp/McpEntityDetail");
    render(shell(createElement(McpEntityDetail)));

    expect(
      screen.getByText(
        "Entity MCP is read-only Business Entity data. It does not write Entity data.",
      ),
    ).toBeTruthy();
    expect(
      screen.getByText(
        "A call needs entity:data_read and an effective read grant. Administrative permission does not bypass Entity grants.",
      ),
    ).toBeTruthy();
    expect(
      screen.getByText(
        "Reads use the caller's Profile Views, the caller's authorized schema.",
      ),
    ).toBeTruthy();
    expect(
      screen.getByText("A visible tool is not access to every Entity."),
    ).toBeTruthy();
    expect(
      screen.queryByText(
        "Metadata MCP is the Source-scoped face for catalog inquiry and living-registry changes.",
      ),
    ).toBeNull();
  });

  it("explains the Entity list, describe, read, validate, and run journey", async () => {
    pathname.current = "/console/mcp/entity";
    const { McpEntityDetail } = await import("@/features/mcp/McpEntityDetail");
    render(shell(createElement(McpEntityDetail)));

    expect(
      screen.getByText(
        "List Entities, describe one Entity, read rows, validate a statement, then run it. Use declared references and the caller's authorized schema.",
      ),
    ).toBeTruthy();
    expect(
      screen.getByText("validate_sql checks a statement and does not promise execution."),
    ).toBeTruthy();
    expect(
      screen.getByText(
        "Masks and withheld cells keep their server meanings. A withheld cell stays null, and its name stays a server mark. This page does not invent totals.",
      ),
    ).toBeTruthy();
  });

  it("shows each endpoint's public URL and a secret-free client configuration", async () => {
    const metadataConfig = `{
  "url": "https://console.example.com/mcp",
  "headers": {
    "Authorization": "Bearer <YOUR_TOKEN>"
  }
}`;
    const entityConfig = `{
  "url": "https://console.example.com/mcp/entity",
  "headers": {
    "Authorization": "Bearer <YOUR_TOKEN>"
  }
}`;

    const { McpMetadataDetail } = await import("@/features/mcp/McpMetadataDetail");
    render(shell(createElement(McpMetadataDetail)));
    expect(screen.getByText("https://console.example.com/mcp")).toBeTruthy();
    expect(screen.getByText(metadataConfig, { collapseWhitespace: false })).toBeTruthy();
    expect(screen.queryByText(entityConfig, { collapseWhitespace: false })).toBeNull();
    expect(document.body.textContent).not.toContain("refraq_");
    cleanup();

    pathname.current = "/console/mcp/entity";
    const { McpEntityDetail } = await import("@/features/mcp/McpEntityDetail");
    render(shell(createElement(McpEntityDetail)));
    expect(screen.getByText("https://console.example.com/mcp/entity")).toBeTruthy();
    expect(screen.getByText(entityConfig, { collapseWhitespace: false })).toBeTruthy();
    expect(screen.queryByText(metadataConfig, { collapseWhitespace: false })).toBeNull();
    expect(document.body.textContent).not.toContain("refraq_");
  });

  it("links to Account for User PAT management and does not collect a token", async () => {
    const { McpMetadataDetail } = await import("@/features/mcp/McpMetadataDetail");
    render(shell(createElement(McpMetadataDetail)));
    expect(
      screen.getByText(
        "Create, list, and revoke a User PAT on Account. This page does not.",
      ),
    ).toBeTruthy();
    expect(screen.getByRole("link", { name: "Open Account" }).getAttribute("href")).toBe(
      "/console/account",
    );
    expect(screen.queryByRole("textbox")).toBeNull();
    expect(document.body.textContent).not.toMatch(/personal access token/i);
    cleanup();

    pathname.current = "/console/mcp/entity";
    const { McpEntityDetail } = await import("@/features/mcp/McpEntityDetail");
    render(shell(createElement(McpEntityDetail)));
    expect(screen.getByRole("link", { name: "Open Account" }).getAttribute("href")).toBe(
      "/console/account",
    );
    expect(screen.queryByRole("textbox")).toBeNull();
  });

  it("separates a REST catalog from a live MCP connection", async () => {
    const { McpMetadataDetail } = await import("@/features/mcp/McpMetadataDetail");
    render(shell(createElement(McpMetadataDetail)));

    expect(
      screen.getByText(
        "GET /mcp/catalog is a REST catalog for this Session. It is not an MCP connection.",
      ),
    ).toBeTruthy();
    expect(
      screen.getByText(
        "A catalog HTTP response does not show MCP process health. A failed catalog request is a catalog failure, not an MCP-host outage.",
      ),
    ).toBeTruthy();
    expect(
      screen.getByText(
        "A 2025-era initialize / Mcp-Session-Id handshake is not this product's protocol. The protocol revision is 2026-07-28.",
      ),
    ).toBeTruthy();
    expect(
      screen.getByText("The supported connection check is a later same-origin browser call."),
    ).toBeTruthy();
    expect(document.body.textContent).not.toMatch(/Inspector/);
    cleanup();

    pathname.current = "/console/mcp/entity";
    const { McpEntityDetail } = await import("@/features/mcp/McpEntityDetail");
    render(shell(createElement(McpEntityDetail)));
    expect(
      screen.getByText(
        "GET /mcp/entity/catalog is a REST catalog for this Session. It is not an MCP connection.",
      ),
    ).toBeTruthy();
    expect(
      screen.queryByText(
        "GET /mcp/catalog is a REST catalog for this Session. It is not an MCP connection.",
      ),
    ).toBeNull();
    expect(document.body.textContent).not.toMatch(/Inspector/);
  });

  it("labels the Session catalog as not connected and shows execution only from the payload", async () => {
    api.mockResolvedValue({
      public_path: "/catalog-supplied",
      tools: [
        {
          name: "set_object_semantics",
          permission: "metadata:write",
          description: "Write object semantics.",
        },
        {
          name: "custom_probe",
          permission: "metadata:read",
          description: "Probe a source.",
          execution: "write",
        },
      ],
    });
    const { McpMetadataDetail } = await import("@/features/mcp/McpMetadataDetail");
    render(shell(createElement(McpMetadataDetail)));

    expect(
      await screen.findByText(
        "Session-projected tool list. This is not an MCP connection and not the callable schema.",
      ),
    ).toBeTruthy();
    expect(api).toHaveBeenCalledWith("/mcp/catalog");
    expect(screen.getByText("https://console.example.com/mcp")).toBeTruthy();
    expect(document.body.textContent).not.toContain("/catalog-supplied");
    expect(screen.getByText("set_object_semantics")).toBeTruthy();
    expect(screen.getByText("metadata:write")).toBeTruthy();
    expect(screen.getByText("Write object semantics.")).toBeTruthy();
    expect(screen.getByText("custom_probe")).toBeTruthy();
    expect(screen.getAllByText("write")).toHaveLength(1);
    expect(screen.queryByRole("button", { name: /tools\/list|tools\/call/i })).toBeNull();
    cleanup();

    api.mockReset();
    api.mockResolvedValue({
      public_path: "/catalog-supplied-entity",
      tools: [
        {
          name: "list_entities",
          permission: "entity:data_read",
          description: "List entities.",
          execution: "read",
        },
      ],
    });
    pathname.current = "/console/mcp/entity";
    const { McpEntityDetail } = await import("@/features/mcp/McpEntityDetail");
    render(shell(createElement(McpEntityDetail)));
    expect(await screen.findByText("list_entities")).toBeTruthy();
    expect(screen.getByText("read")).toBeTruthy();
    expect(screen.getByText("https://console.example.com/mcp/entity")).toBeTruthy();
    expect(document.body.textContent).not.toContain("catalog-supplied");
    expect(api).toHaveBeenCalledWith("/mcp/entity/catalog");
  });

  it("treats an empty tool list as an empty catalog", async () => {
    api.mockResolvedValue({ public_path: "/mcp", tools: [] });
    const { McpMetadataDetail } = await import("@/features/mcp/McpMetadataDetail");
    render(shell(createElement(McpMetadataDetail)));

    expect(
      await screen.findByText("This catalog is empty. That is not an outage."),
    ).toBeTruthy();
    expect(
      screen.queryByText("The catalog request failed. That is not an MCP-host outage."),
    ).toBeNull();
  });

  it("treats a failed catalog request as a catalog failure", async () => {
    api.mockRejectedValue(new Error("catalog down"));
    const { McpMetadataDetail } = await import("@/features/mcp/McpMetadataDetail");
    render(shell(createElement(McpMetadataDetail)));

    expect(
      await screen.findByText(
        "The catalog request failed. That is not an MCP-host outage.",
      ),
    ).toBeTruthy();
    expect(screen.queryByText("This catalog is empty. That is not an outage.")).toBeNull();
  });
});
