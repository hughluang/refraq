/** @vitest-environment jsdom */

import { MantineProvider } from "@mantine/core";
import { render, screen, waitFor } from "@testing-library/react";
import { createElement } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { mcpClientConfig } from "@/features/account/mcp-api";

vi.mock("@refinedev/core", () => ({
  useTranslate: () => (key: string) => key,
  useNotification: () => ({ open: vi.fn() }),
}));

vi.mock("@/lib/api", () => ({
  apiClient: vi.fn().mockResolvedValue({
    public_path: "/mcp",
    tools: [],
  }),
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

  it("shows client config in the code box with the copy control inside", async () => {
    const { McpSection } = await import("@/features/account/McpSection");
    const { container } = render(
      createElement(MantineProvider, null, createElement(McpSection)),
    );

    const expected = mcpClientConfig(window.location.origin, "/mcp");
    const code = await waitFor(() => {
      const el = container.querySelector("pre.mantine-Code-root");
      expect(el?.textContent).toContain("Bearer <YOUR_TOKEN>");
      expect(el?.textContent).toContain(`${window.location.origin}/mcp`);
      return el as HTMLElement;
    });
    expect(code.textContent).toBe(expected);

    const copy = screen.getByRole("button", { name: "account.mcp.copy" });
    expect(copy.hasAttribute("disabled")).toBe(false);
    expect(code.parentElement?.contains(copy)).toBe(true);
    expect(screen.queryByText("account.mcp.urlHint")).toBeNull();

    const writeText = vi.fn().mockResolvedValue(undefined);
    Object.assign(navigator, { clipboard: { writeText } });
    copy.click();
    await waitFor(() => {
      expect(writeText).toHaveBeenCalledWith(expected);
    });
  });
});
