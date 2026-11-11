/**
 * @vitest-environment jsdom
 * @vitest-environment-options {"url": "https://console.example.com/console/mcp/metadata"}
 */

import { MantineProvider } from "@mantine/core";
import { act, cleanup, fireEvent, render, screen, within } from "@testing-library/react";
import { createElement, type ReactNode } from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { McpWorkspaceProvider } from "@/features/mcp/McpWorkspaceProvider";
import en from "@/locales/en-US/common.json";
import zh from "@/locales/zh-CN/common.json";

const copy = en as Record<string, string>;

const api = vi.hoisted(() => vi.fn());
const clipboard = vi.hoisted(() => vi.fn());
const notice = vi.hoisted(() => vi.fn());
const problemNotice = vi.hoisted(() => vi.fn());
vi.mock("@/components/feedback/presentProblemNotification", () => ({ presentProblemNotification: problemNotice }));
vi.mock("@/lib/copy-text", () => ({ copyText: clipboard }));
const pathname = vi.hoisted(() => ({ current: "/console/mcp/metadata" }));

vi.mock("@/lib/api", async () => {
  const actual = await vi.importActual<typeof import("@/lib/api")>("@/lib/api");
  return {
    ...actual,
    apiClient: (...args: unknown[]) => api(...args),
  };
});

vi.mock("@refinedev/core", () => ({
  matchResourceFromRoute: () => ({ found: false }),
  useTranslate: () => (key: string) => copy[key] ?? key,
  useNotification: () => ({ open: notice }),
  useBreadcrumb: () => ({ breadcrumbs: [{ label: "mcp.title", href: "/console/mcp" }, { label: "actions.show" }] }),
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
    notice.mockReset();
    problemNotice.mockReset();
    clipboard.mockReset();
    clipboard.mockResolvedValue(undefined);
    api.mockResolvedValue(undefined);
    pathname.current = "/console/mcp/metadata";
  });

  afterEach(() => {
    cleanup();
  });

  it("keeps MCP locale keys paired and renders translated endpoint crumbs", async () => {
    expect(Object.keys(en).filter((key) => key.startsWith("mcp.")).sort()).toEqual(Object.keys(zh).filter((key) => key.startsWith("mcp.")).sort());
    const original = { ...copy };
    Object.assign(copy, zh);
    try {
      const { McpEntityDetail } = await import("@/features/mcp/McpEntityDetail");
      render(shell(createElement(McpEntityDetail)));
      expect(document.querySelector('[aria-current="page"]')?.textContent).toBe(zh["mcp.entity.title"]);
      expect(screen.getByRole("heading", { name: zh["mcp.connection.title"] })).toBeTruthy();
      expect(screen.getByRole("button", { name: zh["mcp.copy.config"] })).toBeTruthy();
    } finally { Object.assign(copy, original); }
  });

  it("copies only the public URL and placeholder configuration with shared feedback", async () => {
    api.mockResolvedValue({ tools: [] });
    const { McpMetadataDetail } = await import("@/features/mcp/McpMetadataDetail");
    render(shell(createElement(McpMetadataDetail)));
    fireEvent.change(screen.getByLabelText("Personal access token"), { target: { value: "memory-only-clipboard-secret" } });
    const button = screen.getByRole("button", { name: "Copy endpoint URL" });
    button.focus();
    await act(async () => { fireEvent.click(button); });
    expect(clipboard).toHaveBeenLastCalledWith("https://console.example.com/mcp");
    expect(document.activeElement).toBe(button);
    expect(notice).toHaveBeenLastCalledWith({ type: "success", message: copy["common.copy.success"] });
    await act(async () => { fireEvent.click(screen.getByRole("button", { name: "Copy configuration" })); });
    expect(clipboard).toHaveBeenLastCalledWith('{\n  "url": "https://console.example.com/mcp",\n  "headers": {\n    "Authorization": "Bearer <YOUR_TOKEN>"\n  }\n}');
    clipboard.mockRejectedValueOnce(new Error("denied"));
    await act(async () => { fireEvent.click(button); });
    expect(notice).toHaveBeenLastCalledWith({ type: "error", message: copy["common.copy.failed"] });
  });

  it("retries only the Session catalog and distinguishes pending from empty", async () => {
    let release: (value: unknown) => void = () => {};
    api.mockReturnValueOnce(new Promise((resolve) => { release = resolve; }));
    const { McpMetadataDetail } = await import("@/features/mcp/McpMetadataDetail");
    render(shell(createElement(McpMetadataDetail)));
    expect(screen.getByText("Loading Session tool catalog…")).toBeTruthy();
    expect(screen.queryByText(copy["mcp.catalog.empty"])).toBeNull();
    await act(async () => { release(undefined); });
    const retry = await screen.findByRole("button", { name: "Not loaded" });
    fireEvent.change(screen.getByLabelText("Personal access token"), { target: { value: "memory-only-test" } });
    api.mockResolvedValueOnce({ tools: [] });
    fireEvent.click(retry);
    expect(await screen.findByText(copy["mcp.catalog.empty"])).toBeTruthy();
    expect(api.mock.calls.filter((call) => String(call[0]).includes("/catalog"))).toEqual([
      ["/mcp/catalog"],
      ["/mcp/catalog"],
    ]);
    expect((screen.getByLabelText("Personal access token") as HTMLInputElement).value).toBe("memory-only-test");
  });

  it("ignores notification retries after their catalog request has been replaced", async () => {
    api.mockRejectedValueOnce(new Error("catalog down"));
    const { McpClientConfiguration } = await import("@/features/mcp/McpClientConfiguration");
    const view = render(shell(createElement(McpClientConfiguration, { publicPath: "/mcp" })));
    await screen.findByRole("button", { name: "Not loaded" });
    const retry = problemNotice.mock.calls[0][2].onRetry as () => void;
    api.mockResolvedValue({ tools: [] });
    const catalogCalls = () =>
      api.mock.calls.filter((call) => String(call[0]).includes("/catalog"));
    await act(async () => { retry(); });
    expect(catalogCalls()).toEqual([["/mcp/catalog"], ["/mcp/catalog"]]);
    await act(async () => { retry(); });
    expect(catalogCalls()).toHaveLength(2);
    view.rerender(shell(createElement(McpClientConfiguration, { publicPath: "/mcp/entity" })));
    await screen.findByText(copy["mcp.catalog.empty"]);
    expect(catalogCalls()).toEqual([
      ["/mcp/catalog"],
      ["/mcp/catalog"],
      ["/mcp/entity/catalog"],
    ]);
    await act(async () => { retry(); });
    expect(catalogCalls()).toHaveLength(3);
    view.unmount();
    await act(async () => { retry(); });
    expect(catalogCalls()).toHaveLength(3);
  });

  it("ignores a late catalog response after switching endpoint", async () => {
    let release: (value: unknown) => void = () => {};
    api.mockReturnValueOnce(new Promise((resolve) => { release = resolve; }));
    const { McpClientConfiguration } = await import("@/features/mcp/McpClientConfiguration");
    const view = render(shell(createElement(McpClientConfiguration, { publicPath: "/mcp" })));
    api.mockResolvedValueOnce({ tools: [] });
    view.rerender(shell(createElement(McpClientConfiguration, { publicPath: "/mcp/entity" })));
    await screen.findByText(copy["mcp.catalog.empty"]);
    await act(async () => { release({ tools: [{ name: "stale-tool", description: "Stale", permission: "metadata:read" }] }); });
    expect(screen.queryByText("stale-tool")).toBeNull();
    expect(problemNotice).not.toHaveBeenCalled();
  });

  it("gives both endpoints named sections and header navigation", async () => {
    const { McpMetadataDetail } = await import("@/features/mcp/McpMetadataDetail");
    render(shell(createElement(McpMetadataDetail)));
    expect(screen.getAllByRole("heading", { level: 1 })).toHaveLength(1);
    for (const name of ["Connection setup", "Test with your personal access token", "Tool catalog"]) {
      expect(screen.getByRole("heading", { name, level: 2 })).toBeTruthy();
    }
    expect(document.querySelector("[data-page-header]")?.contains(screen.getByRole("link", { name: "Back to MCP" }))).toBe(true);
    expect(screen.getByText("Browse Source catalogs, maintain semantics and joins, and run controlled read-only SQL.")).toBeTruthy();
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
        copy["mcp.entity.masks"],
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
        "Create, list, and revoke a personal access token on Account. This page does not.",
      ),
    ).toBeTruthy();
    expect(screen.getByRole("link", { name: "Open Account" }).getAttribute("href")).toBe(
      "/console/account",
    );
    expect(screen.queryByRole("textbox")).toBeNull();
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
      screen.getByText(
        "The supported connection check is this page's same-origin verify and discover.",
      ),
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
    expect(await screen.findByText("set_object_semantics")).toBeTruthy();
    const catalogRow = screen.getByText("set_object_semantics").closest("li");
    expect(catalogRow?.textContent).toContain("metadata:write");
    expect(catalogRow?.textContent).toContain("Write object semantics.");
    expect(catalogRow?.textContent).toContain("Execution class is not published.");
    expect(screen.getByText("custom_probe").closest("li")?.textContent).toContain("write");
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
      await screen.findByText(copy["mcp.catalog.empty"]),
    ).toBeTruthy();
    expect(screen.queryByRole("button", { name: "Not loaded" })).toBeNull();
  });

  it("treats a failed catalog request as a catalog failure", async () => {
    api.mockRejectedValue(new Error("catalog down"));
    const { McpMetadataDetail } = await import("@/features/mcp/McpMetadataDetail");
    render(shell(createElement(McpMetadataDetail)));

    expect(
      await screen.findByRole("button", { name: "Not loaded" }),
    ).toBeTruthy();
    expect(screen.getByText("Streamable HTTP · 2026-07-28")).toBeTruthy();
    expect(screen.queryByText(copy["mcp.catalog.empty"])).toBeNull();
    expect(screen.queryByRole("button", { name: "Retry Session catalog" })).toBeNull();
  });
});
