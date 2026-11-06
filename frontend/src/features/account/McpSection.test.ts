/** @vitest-environment jsdom */

import { MantineProvider } from "@mantine/core";
import { cleanup, render, screen, waitFor } from "@testing-library/react";
import { createElement } from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { mcpClientConfig } from "@/features/account/mcp-api";

vi.mock("@refinedev/core", () => ({
  useTranslate: () => (key: string) => key,
  useNotification: () => ({ open: vi.fn() }),
}));

const { apiClient } = vi.hoisted(() => ({
  apiClient: vi.fn((path: string) => {
    if (path === "/mcp/entity/catalog") {
      return Promise.resolve({
        public_path: "/mcp/entity",
        tools: [
          {
            name: "list_entities",
            permission: "entity:data_read",
            description: "Entities the caller can read",
          },
        ],
      });
    }
    if (path === "/mcp/catalog") {
      return Promise.resolve({
        public_path: "/mcp",
        tools: [],
      });
    }
    return Promise.reject(new Error(`unexpected ${path}`));
  }),
}));

vi.mock("@/lib/api", () => ({
  apiClient,
  ApiError: class ApiError extends Error {},
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

describe("McpSection", () => {
  beforeEach(() => {
    stubDomApis();
  });

  afterEach(() => {
    cleanup();
  });

  it("shows client config in the code box with the copy control inside", async () => {
    const { McpSection } = await import("@/features/account/McpSection");
    const { container } = render(
      createElement(MantineProvider, null, createElement(McpSection)),
    );

    const metadataConfig = mcpClientConfig(window.location.origin, "/mcp");
    const entityConfig = mcpClientConfig(
      window.location.origin,
      "/mcp/entity",
    );
    const codes = await waitFor(() => {
      const nodes = [
        ...container.querySelectorAll("pre.mantine-Code-root"),
      ];
      expect(nodes).toHaveLength(2);
      expect(screen.getByText("list_entities")).toBeTruthy();
      return nodes;
    });
    expect(codes[0]?.textContent).toBe(metadataConfig);
    expect(codes[1]?.textContent).toBe(entityConfig);
    expect(apiClient).toHaveBeenCalledWith("/mcp/catalog");
    expect(apiClient).toHaveBeenCalledWith("/mcp/entity/catalog");

    expect(screen.getByText("account.mcp.metadata.title")).toBeTruthy();
    expect(screen.getByText("account.mcp.metadata.description")).toBeTruthy();
    expect(screen.getByText("account.mcp.entity.title")).toBeTruthy();
    expect(screen.getByText("account.mcp.entity.description")).toBeTruthy();
    expect(screen.getByText("list_entities")).toBeTruthy();
    expect(screen.getByText("entity:data_read")).toBeTruthy();
    expect(screen.getAllByText("account.mcp.tools.empty")).toHaveLength(1);

    const copies = screen.getAllByRole("button", { name: "account.mcp.copy" });
    expect(copies).toHaveLength(2);
    expect(codes[0]?.parentElement?.contains(copies[0] ?? null)).toBe(true);
    expect(codes[1]?.parentElement?.contains(copies[1] ?? null)).toBe(true);
    expect(screen.queryByText("account.mcp.urlHint")).toBeNull();

    const writeText = vi.fn().mockResolvedValue(undefined);
    Object.defineProperty(window, "isSecureContext", {
      configurable: true,
      value: true,
    });
    Object.assign(navigator, { clipboard: { writeText } });
    copies[0]?.click();
    copies[1]?.click();
    await waitFor(() => {
      expect(writeText).toHaveBeenCalledWith(metadataConfig);
      expect(writeText).toHaveBeenCalledWith(entityConfig);
    });
  });
});
