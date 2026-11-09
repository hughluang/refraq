/**
 * @vitest-environment jsdom
 * @vitest-environment-options {"url": "https://console.example.com/console/mcp/metadata"}
 */

import { MantineProvider } from "@mantine/core";
import { act, cleanup, fireEvent, render, screen, within } from "@testing-library/react";
import { createElement, type ReactNode } from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import en from "@/locales/en-US/common.json";
import {
  resetSessionStoreForTests,
  useSessionStore,
  type CurrentUser,
} from "@/providers/session-store";

const copy = en as Record<string, string>;
const api = vi.hoisted(() => vi.fn());

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

const pathname = vi.hoisted(() => ({ current: "/console/mcp/metadata" }));

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

const PAT = "rfqpat-distinct-secret-05";
const apiBase = process.env.NEXT_PUBLIC_REFRAQ_API_BASE_URL || "/api";
const ORIGIN = "https://console.example.com";

function sessionUser(id: string): CurrentUser {
  return {
    id,
    account: "ada",
    display_name: "Ada",
    email: null,
    locale: "en-US",
    display_timezone: null,
    role_id: null,
    role_key: null,
    role_name: null,
    permissions: ["console:access"],
    identity_source: "local",
  };
}

function jsonResponse(status: number, body: unknown, contentType = "application/json") {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": contentType },
  });
}

function meBody(id: string) {
  return {
    user: {
      id,
      account: "other-account",
      display_name: "Pat Owner",
      email: null,
      locale: "zh-CN",
      display_timezone: null,
      role_id: null,
      role_key: null,
      role_name: null,
      permissions: [],
      identity_source: "local",
    },
  };
}

function shell(node: ReactNode) {
  return createElement(MantineProvider, { env: "test" }, node);
}

function toolMessage(
  id: unknown,
  tools: unknown[],
) {
  return {
    jsonrpc: "2.0",
    id,
    result: { tools },
  };
}

function metadataTools(id: unknown) {
  return toolMessage(id, [
    {
      name: "run_sql",
      description: "Run controlled SQL.",
      inputSchema: {
        type: "object",
        properties: { statement: { type: "string" } },
      },
      annotations: { readOnlyHint: true },
      _meta: { "io.refraq/execution": "read" },
    },
    {
      name: "set_object_semantics",
      description: "Write object semantics.",
      inputSchema: {
        type: "object",
        properties: { object_id: { type: "string" } },
      },
      _meta: { "io.refraq/execution": "write" },
    },
    {
      name: "search_sources",
      description: "Find sources.",
      inputSchema: {
        type: "object",
        properties: { keywords: { type: "string" } },
      },
      execution: "read",
      annotations: { readOnlyHint: true },
    },
  ]);
}

async function renderMetadata() {
  const { default: Layout } = await import("@/app/console/mcp/layout");
  const { McpMetadataDetail } = await import("@/features/mcp/McpMetadataDetail");
  return render(shell(createElement(Layout, null, createElement(McpMetadataDetail))));
}

async function renderEntityDetail() {
  const { McpEntityDetail } = await import("@/features/mcp/McpEntityDetail");
  return createElement(McpEntityDetail);
}

function requestId(call: unknown[]): unknown {
  const init = call[1] as RequestInit | undefined;
  const body = typeof init?.body === "string" ? JSON.parse(init.body) : {};
  return body.id;
}

function sseMessage(id: unknown, tools: unknown[]): string {
  return `event: message\ndata: ${JSON.stringify(toolMessage(id, tools))}`;
}

function entityRunSql(id: unknown) {
  return toolMessage(id, [
    {
      name: "run_sql",
      description: "Run entity SQL.",
      inputSchema: {
        type: "object",
        properties: { query: { type: "string" } },
      },
      annotations: { readOnlyHint: true },
      _meta: { "io.refraq/execution": "read" },
    },
  ]);
}

function verifyPat() {
  fireEvent.change(screen.getByLabelText("User PAT"), { target: { value: PAT } });
  fireEvent.click(screen.getByRole("button", { name: "Verify User PAT" }));
}

function toolsListCalls() {
  return vi.mocked(fetch).mock.calls.filter((call) => {
    const init = call[1] as RequestInit | undefined;
    if (!init || init.method !== "POST") return false;
    const body = typeof init.body === "string" ? init.body : "";
    return body.includes('"tools/list"');
  });
}

describe("MCP live tools/list discovery", () => {
  beforeEach(() => {
    stubDomApis();
    localStorage.clear();
    sessionStorage.clear();
    pathname.current = "/console/mcp/metadata";
    resetSessionStoreForTests();
    useSessionStore.setState({
      user: sessionUser("user-a"),
      permissionsReady: true,
    });
    api.mockReset();
    api.mockResolvedValue({
      tools: [
        {
          name: "run_sql",
          permission: "metadata:read",
          description: "Catalog copy of run sql.",
          execution: "write",
        },
      ],
    });
    vi.stubGlobal(
      "fetch",
      vi.fn(async (url: string, init?: RequestInit) => {
        if (String(url).endsWith("/auth/me")) {
          return jsonResponse(200, meBody("user-a"));
        }
        const body = typeof init?.body === "string" ? JSON.parse(init.body) : {};
        return jsonResponse(200, metadataTools(body.id));
      }),
    );
  });

  afterEach(() => {
    cleanup();
    resetSessionStoreForTests();
    vi.unstubAllGlobals();
    vi.restoreAllMocks();
  });

  it("lists the selected endpoint's tools only after the user asks", async () => {
    await renderMetadata();

    expect(screen.queryByRole("button", { name: "Discover tools" })).toBeNull();
    expect(toolsListCalls()).toHaveLength(0);
    expect(
      screen.getByText(
        "Session-projected tool list. This is not an MCP connection and not the callable schema.",
      ),
    ).toBeTruthy();

    verifyPat();
    expect(
      await screen.findByText("This User PAT belongs to the signed-in user. user-a"),
    ).toBeTruthy();
    expect(toolsListCalls()).toHaveLength(0);
    expect(screen.queryByText("Run controlled SQL.")).toBeNull();
    expect(await screen.findByText("Catalog copy of run sql.")).toBeTruthy();
    expect(api).toHaveBeenCalledWith("/mcp/catalog");

    fireEvent.click(screen.getByRole("button", { name: "Discover tools" }));

    const runSql = await screen.findByRole("listitem", { name: "/mcp run_sql" });
    expect(within(runSql).getByText("Run controlled SQL.")).toBeTruthy();
    expect(within(runSql).getByText(/"statement"/)).toBeTruthy();
    expect(within(runSql).getByText("read")).toBeTruthy();
    expect(within(runSql).queryByText("Catalog copy of run sql.")).toBeNull();
    expect(within(runSql).queryByText("write")).toBeNull();

    const writeTool = screen.getByRole("listitem", { name: "/mcp set_object_semantics" });
    expect(within(writeTool).getByText("Write object semantics.")).toBeTruthy();
    expect(within(writeTool).getByText(/"object_id"/)).toBeTruthy();
    expect(within(writeTool).getByText("write")).toBeTruthy();

    const unclassified = screen.getByRole("listitem", { name: "/mcp search_sources" });
    expect(within(unclassified).getByText("Find sources.")).toBeTruthy();
    expect(within(unclassified).getByText(/"keywords"/)).toBeTruthy();
    expect(within(unclassified).getByText("Execution class is not published.")).toBeTruthy();
    expect(within(unclassified).queryByText("read")).toBeNull();

    expect(screen.getByText("Catalog copy of run sql.")).toBeTruthy();
    expect(screen.queryByRole("listitem", { name: "/mcp/entity run_sql" })).toBeNull();

    const listed = toolsListCalls();
    expect(listed).toHaveLength(1);
    expect(String(listed[0][0])).toBe(`${ORIGIN}/mcp`);
    const init = listed[0][1] as RequestInit;
    expect(init.method).toBe("POST");
    expect(init.credentials).toBe("omit");
    const headers = new Headers(init.headers);
    expect(headers.get("Authorization")).toBe(`Bearer ${PAT}`);
    expect(headers.get("Content-Type")).toBe("application/json");
    expect(headers.get("Accept")).toContain("application/json");
    expect(headers.get("Accept")).toContain("text/event-stream");
    expect(headers.get("mcp-protocol-version")).toBe("2026-07-28");
    expect(headers.get("mcp-method")).toBe("tools/list");
    expect(headers.has("mcp-name")).toBe(false);
    expect(headers.has("Mcp-Session-Id")).toBe(false);
    const payload = JSON.parse(String(init.body)) as {
      jsonrpc: string;
      id: unknown;
      method: string;
      params: { _meta: Record<string, unknown> };
    };
    expect(payload.jsonrpc).toBe("2.0");
    expect(payload.method).toBe("tools/list");
    expect(payload.params._meta["io.modelcontextprotocol/protocolVersion"]).toBe("2026-07-28");
    expect(payload.params._meta["io.modelcontextprotocol/clientCapabilities"]).toEqual({});
    expect(payload.id).not.toBeUndefined();
    const methods = vi
      .mocked(fetch)
      .mock.calls.map((call) => {
        const body = (call[1] as RequestInit | undefined)?.body;
        return typeof body === "string" ? body : "";
      })
      .join("\n");
    expect(methods).not.toContain("tools/call");
    expect(methods).not.toContain("initialize");
    expect(String(listed[0][0]).startsWith(apiBase)).toBe(false);
    expect(screen.queryByRole("button", { name: /tools\/call/i })).toBeNull();
  });

  it("keeps each endpoint's tools distinct and leaves the User PAT in place", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async (url: string, init?: RequestInit) => {
        if (String(url).endsWith("/auth/me")) return jsonResponse(200, meBody("user-a"));
        const body = typeof init?.body === "string" ? JSON.parse(init.body) : {};
        if (String(url) === `${ORIGIN}/mcp/entity`) return jsonResponse(200, entityRunSql(body.id));
        return jsonResponse(200, metadataTools(body.id));
      }),
    );
    const view = await renderMetadata();
    verifyPat();
    await screen.findByRole("button", { name: "Discover tools" });
    fireEvent.click(screen.getByRole("button", { name: "Discover tools" }));
    expect(await screen.findByRole("listitem", { name: "/mcp run_sql" })).toBeTruthy();

    pathname.current = "/console/mcp/entity";
    view.rerender(
      shell(
        createElement(
          (await import("@/app/console/mcp/layout")).default,
          null,
          await renderEntityDetail(),
        ),
      ),
    );

    expect((screen.getByLabelText("User PAT") as HTMLInputElement).value).toBe(PAT);
    expect(screen.getByText("Selected endpoint /mcp/entity")).toBeTruthy();
    expect(screen.queryByRole("listitem", { name: "/mcp run_sql" })).toBeNull();
    expect(screen.queryByText("Run controlled SQL.")).toBeNull();
    expect(toolsListCalls()).toHaveLength(1);

    fireEvent.click(screen.getByRole("button", { name: "Discover tools" }));
    const entitySql = await screen.findByRole("listitem", { name: "/mcp/entity run_sql" });
    expect(within(entitySql).getByText("Run entity SQL.")).toBeTruthy();
    expect(within(entitySql).getByText(/"query"/)).toBeTruthy();
    expect(within(entitySql).getByText("read")).toBeTruthy();
    expect(screen.queryByRole("listitem", { name: "/mcp run_sql" })).toBeNull();
    expect(screen.queryByText(/"statement"/)).toBeNull();

    const entityCall = toolsListCalls().at(-1);
    expect(entityCall).toBeTruthy();
    expect(String(entityCall?.[0])).toBe(`${ORIGIN}/mcp/entity`);
    const headers = new Headers((entityCall?.[1] as RequestInit).headers);
    expect(headers.get("mcp-method")).toBe("tools/list");
    expect(headers.has("mcp-name")).toBe(false);
    expect((entityCall?.[1] as RequestInit).credentials).toBe("omit");

    pathname.current = "/console/mcp/metadata";
    const { McpMetadataDetail } = await import("@/features/mcp/McpMetadataDetail");
    view.rerender(
      shell(
        createElement(
          (await import("@/app/console/mcp/layout")).default,
          null,
          createElement(McpMetadataDetail),
        ),
      ),
    );
    expect(screen.queryByRole("listitem", { name: "/mcp run_sql" })).toBeNull();
    expect(screen.queryByText("Run controlled SQL.")).toBeNull();
    expect(screen.queryByText(/"statement"/)).toBeNull();
    expect(screen.queryByRole("listitem", { name: "/mcp/entity run_sql" })).toBeNull();
    expect(screen.queryByText("Run entity SQL.")).toBeNull();
    expect((screen.getByLabelText("User PAT") as HTMLInputElement).value).toBe(PAT);

    fireEvent.click(screen.getByRole("button", { name: "Discover tools" }));
    expect(await screen.findByRole("listitem", { name: "/mcp run_sql" })).toBeTruthy();
    expect(screen.queryByRole("listitem", { name: "/mcp/entity run_sql" })).toBeNull();
  });

  it("clears the tool list when the detail endpoint changes until discover runs again", async () => {
    const view = await renderMetadata();
    verifyPat();
    await screen.findByRole("button", { name: "Discover tools" });
    fireEvent.click(screen.getByRole("button", { name: "Discover tools" }));
    expect(await screen.findByRole("listitem", { name: "/mcp run_sql" })).toBeTruthy();

    pathname.current = "/console/mcp/entity";
    view.rerender(
      shell(
        createElement(
          (await import("@/app/console/mcp/layout")).default,
          null,
          await renderEntityDetail(),
        ),
      ),
    );
    expect(screen.queryByRole("listitem", { name: "/mcp run_sql" })).toBeNull();
    expect(screen.queryByText("Run controlled SQL.")).toBeNull();
    expect(screen.queryByText(/"statement"/)).toBeNull();
    expect((screen.getByLabelText("User PAT") as HTMLInputElement).value).toBe(PAT);

    pathname.current = "/console/mcp/metadata";
    const { McpMetadataDetail } = await import("@/features/mcp/McpMetadataDetail");
    view.rerender(
      shell(
        createElement(
          (await import("@/app/console/mcp/layout")).default,
          null,
          createElement(McpMetadataDetail),
        ),
      ),
    );
    expect(screen.queryByRole("listitem", { name: "/mcp run_sql" })).toBeNull();
    expect(screen.queryByText("Run controlled SQL.")).toBeNull();
    expect(screen.queryByText(/"statement"/)).toBeNull();
    expect((screen.getByLabelText("User PAT") as HTMLInputElement).value).toBe(PAT);

    const listed = toolsListCalls().length;
    fireEvent.click(screen.getByRole("button", { name: "Discover tools" }));
    expect(await screen.findByRole("listitem", { name: "/mcp run_sql" })).toBeTruthy();
    expect(toolsListCalls().length).toBe(listed + 1);
  });

  it("keeps the tool list when the overview opens without another endpoint", async () => {
    const view = await renderMetadata();
    verifyPat();
    await screen.findByRole("button", { name: "Discover tools" });
    fireEvent.click(screen.getByRole("button", { name: "Discover tools" }));
    expect(await screen.findByRole("listitem", { name: "/mcp run_sql" })).toBeTruthy();

    pathname.current = "/console/mcp";
    const { McpOverview } = await import("@/features/mcp/McpOverview");
    view.rerender(
      shell(
        createElement(
          (await import("@/app/console/mcp/layout")).default,
          null,
          createElement(McpOverview),
        ),
      ),
    );
    expect(screen.queryByRole("listitem", { name: "/mcp run_sql" })).toBeNull();

    pathname.current = "/console/mcp/metadata";
    const { McpMetadataDetail } = await import("@/features/mcp/McpMetadataDetail");
    view.rerender(
      shell(
        createElement(
          (await import("@/app/console/mcp/layout")).default,
          null,
          createElement(McpMetadataDetail),
        ),
      ),
    );
    expect(screen.getByRole("listitem", { name: "/mcp run_sql" })).toBeTruthy();
    expect((screen.getByLabelText("User PAT") as HTMLInputElement).value).toBe(PAT);
    expect(toolsListCalls()).toHaveLength(1);
  });

  it("drops an in-flight tools/list when the detail endpoint changes", async () => {
    let release: (response: Response) => void = () => {};
    let heldId: unknown = 0;
    let holdNextList = false;
    vi.stubGlobal(
      "fetch",
      vi.fn(async (url: string, init?: RequestInit) => {
        if (String(url).endsWith("/auth/me")) return jsonResponse(200, meBody("user-a"));
        const id = requestId([url, init]);
        if (!holdNextList) return jsonResponse(200, metadataTools(id));
        heldId = id;
        return new Promise<Response>((resolve) => {
          release = resolve;
        });
      }),
    );
    const view = await renderMetadata();
    verifyPat();
    await screen.findByRole("button", { name: "Discover tools" });
    fireEvent.click(screen.getByRole("button", { name: "Discover tools" }));
    expect(await screen.findByRole("listitem", { name: "/mcp run_sql" })).toBeTruthy();

    holdNextList = true;
    fireEvent.click(screen.getByRole("button", { name: "Discover tools" }));
    pathname.current = "/console/mcp/entity";
    view.rerender(
      shell(
        createElement(
          (await import("@/app/console/mcp/layout")).default,
          null,
          await renderEntityDetail(),
        ),
      ),
    );
    pathname.current = "/console/mcp/metadata";
    const { McpMetadataDetail } = await import("@/features/mcp/McpMetadataDetail");
    view.rerender(
      shell(
        createElement(
          (await import("@/app/console/mcp/layout")).default,
          null,
          createElement(McpMetadataDetail),
        ),
      ),
    );

    expect(screen.queryByRole("listitem", { name: "/mcp run_sql" })).toBeNull();
    await act(async () => {
      release(jsonResponse(200, metadataTools(heldId)));
    });
    expect(screen.queryByRole("listitem", { name: "/mcp run_sql" })).toBeNull();
    expect(screen.queryByText("Run controlled SQL.")).toBeNull();
    expect((screen.getByLabelText("User PAT") as HTMLInputElement).value).toBe(PAT);
  });

  it("treats an empty tools/list as an empty catalog", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async (url: string, init?: RequestInit) => {
        if (String(url).endsWith("/auth/me")) return jsonResponse(200, meBody("user-a"));
        const id = requestId([url, init]);
        return jsonResponse(200, toolMessage(id, []));
      }),
    );
    await renderMetadata();
    verifyPat();
    await screen.findByRole("button", { name: "Discover tools" });
    fireEvent.click(screen.getByRole("button", { name: "Discover tools" }));

    expect(
      await screen.findByText("This endpoint returned no tools. That is an empty catalog."),
    ).toBeTruthy();
    expect(screen.queryByText("This endpoint is unavailable.")).toBeNull();
    expect(
      screen.queryByText("The tool list response could not be read. That is not an empty catalog."),
    ).toBeNull();
    expect(
      screen.getByText(
        "Session-projected tool list. This is not an MCP connection and not the callable schema.",
      ),
    ).toBeTruthy();
    expect(screen.getByText("Catalog copy of run sql.")).toBeTruthy();
  });

  it("reads a matching SSE message and ignores a different JSON-RPC id", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async (url: string, init?: RequestInit) => {
        if (String(url).endsWith("/auth/me")) return jsonResponse(200, meBody("user-a"));
        const id = requestId([url, init]);
        const body = [
          ": ping",
          `event: message\ndata: ${JSON.stringify({ jsonrpc: "2.0", method: "notifications/progress" })}`,
          sseMessage(999999, []),
          sseMessage(id, [
            {
              name: "run_sql",
              description: "Streamed SQL.",
              inputSchema: { type: "object", properties: { streamed: { type: "boolean" } } },
              _meta: { "io.refraq/execution": "read" },
            },
          ]),
        ].join("\n\n");
        return new Response(`${body}\n\n`, {
          status: 200,
          headers: { "Content-Type": "text/event-stream" },
        });
      }),
    );
    await renderMetadata();
    verifyPat();
    await screen.findByRole("button", { name: "Discover tools" });
    fireEvent.click(screen.getByRole("button", { name: "Discover tools" }));

    const runSql = await screen.findByRole("listitem", { name: "/mcp run_sql" });
    expect(within(runSql).getByText("Streamed SQL.")).toBeTruthy();
    expect(within(runSql).getByText(/"streamed"/)).toBeTruthy();
    expect(
      screen.queryByText("This endpoint returned no tools. That is an empty catalog."),
    ).toBeNull();
  });

  it("reports a protocol error without turning it into an empty catalog", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async (url: string, init?: RequestInit) => {
        if (String(url).endsWith("/auth/me")) return jsonResponse(200, meBody("user-a"));
        const id = requestId([url, init]);
        return jsonResponse(400, {
          jsonrpc: "2.0",
          id,
          error: { code: -32603, message: "hidden-rpc-detail" },
        });
      }),
    );
    await renderMetadata();
    verifyPat();
    await screen.findByRole("button", { name: "Discover tools" });
    fireEvent.click(screen.getByRole("button", { name: "Discover tools" }));

    expect(await screen.findByText("This endpoint returned a protocol error.")).toBeTruthy();
    expect(screen.queryByText("hidden-rpc-detail")).toBeNull();
    expect(
      screen.queryByText("This endpoint returned no tools. That is an empty catalog."),
    ).toBeNull();
    expect(document.body.textContent).not.toContain(PAT);
  });

  it("does not present a non-success SSE list as a catalog", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async (url: string, init?: RequestInit) => {
        if (String(url).endsWith("/auth/me")) return jsonResponse(200, meBody("user-a"));
        const id = requestId([url, init]);
        const body = sseMessage(id, [
          {
            name: "run_sql",
            description: "Failed stream SQL.",
            inputSchema: { type: "object", properties: { streamed: { type: "boolean" } } },
            _meta: { "io.refraq/execution": "read" },
          },
        ]);
        return new Response(`${body}\n\n`, {
          status: 500,
          headers: { "Content-Type": "text/event-stream" },
        });
      }),
    );
    await renderMetadata();
    verifyPat();
    await screen.findByRole("button", { name: "Discover tools" });
    fireEvent.click(screen.getByRole("button", { name: "Discover tools" }));

    expect(await screen.findByText("This endpoint is unavailable.")).toBeTruthy();
    expect(screen.queryByText("Failed stream SQL.")).toBeNull();
    expect(
      screen.queryByText("This endpoint returned no tools. That is an empty catalog."),
    ).toBeNull();
    expect(
      screen.queryByText("The tool list response could not be read. That is not an empty catalog."),
    ).toBeNull();
    cleanup();

    vi.stubGlobal(
      "fetch",
      vi.fn(async (url: string, init?: RequestInit) => {
        if (String(url).endsWith("/auth/me")) return jsonResponse(200, meBody("user-a"));
        const id = requestId([url, init]);
        return new Response(`${sseMessage(id, [])}\n\n`, {
          status: 500,
          headers: { "Content-Type": "text/event-stream" },
        });
      }),
    );
    await renderMetadata();
    verifyPat();
    await screen.findByRole("button", { name: "Discover tools" });
    fireEvent.click(screen.getByRole("button", { name: "Discover tools" }));
    expect(await screen.findByText("This endpoint is unavailable.")).toBeTruthy();
    expect(
      screen.queryByText("This endpoint returned no tools. That is an empty catalog."),
    ).toBeNull();
    cleanup();

    vi.stubGlobal(
      "fetch",
      vi.fn(async (url: string, init?: RequestInit) => {
        if (String(url).endsWith("/auth/me")) return jsonResponse(200, meBody("user-a"));
        const id = requestId([url, init]);
        const body = `event: message\ndata: ${JSON.stringify({
          jsonrpc: "2.0",
          id,
          error: { code: -32603, message: "hidden-sse-detail" },
        })}`;
        return new Response(`${body}\n\n`, {
          status: 400,
          headers: { "Content-Type": "text/event-stream" },
        });
      }),
    );
    await renderMetadata();
    verifyPat();
    await screen.findByRole("button", { name: "Discover tools" });
    fireEvent.click(screen.getByRole("button", { name: "Discover tools" }));

    expect(await screen.findByText("This endpoint returned a protocol error.")).toBeTruthy();
    expect(screen.queryByText("hidden-sse-detail")).toBeNull();
    expect(screen.queryByText("This endpoint is unavailable.")).toBeNull();
  });

  it("keeps an endpoint outage on that endpoint", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async (url: string, init?: RequestInit) => {
        if (String(url).endsWith("/auth/me")) return jsonResponse(200, meBody("user-a"));
        const id = requestId([url, init]);
        if (String(url) === `${ORIGIN}/mcp/entity`) {
          return jsonResponse(502, { error: "mcp_upstream_unavailable" });
        }
        return jsonResponse(200, metadataTools(id));
      }),
    );
    const view = await renderMetadata();
    verifyPat();
    await screen.findByRole("button", { name: "Discover tools" });
    fireEvent.click(screen.getByRole("button", { name: "Discover tools" }));
    expect(await screen.findByRole("listitem", { name: "/mcp run_sql" })).toBeTruthy();

    pathname.current = "/console/mcp/entity";
    view.rerender(
      shell(
        createElement(
          (await import("@/app/console/mcp/layout")).default,
          null,
          await renderEntityDetail(),
        ),
      ),
    );
    fireEvent.click(screen.getByRole("button", { name: "Discover tools" }));
    expect(await screen.findByText("This endpoint is unavailable.")).toBeTruthy();
    expect(screen.queryByText("mcp_upstream_unavailable")).toBeNull();
    expect(screen.queryByRole("listitem", { name: "/mcp run_sql" })).toBeNull();
    expect(
      screen.queryByText("This endpoint returned no tools. That is an empty catalog."),
    ).toBeNull();

    pathname.current = "/console/mcp/metadata";
    const { McpMetadataDetail } = await import("@/features/mcp/McpMetadataDetail");
    view.rerender(
      shell(
        createElement(
          (await import("@/app/console/mcp/layout")).default,
          null,
          createElement(McpMetadataDetail),
        ),
      ),
    );
    expect(screen.queryByRole("listitem", { name: "/mcp run_sql" })).toBeNull();
    expect(screen.queryByText("Run controlled SQL.")).toBeNull();
    expect(screen.queryByText("This endpoint is unavailable.")).toBeNull();
    const methods = vi
      .mocked(fetch)
      .mock.calls.map((call) => String((call[1] as RequestInit | undefined)?.body ?? ""))
      .join("\n");
    expect(methods).not.toContain("tools/call");
  });

  it("reports HTTP and network failures for the selected endpoint", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async (url: string) => {
        if (String(url).endsWith("/auth/me")) return jsonResponse(200, meBody("user-a"));
        return jsonResponse(500, { detail: "hidden-http-detail" });
      }),
    );
    await renderMetadata();
    verifyPat();
    await screen.findByRole("button", { name: "Discover tools" });
    fireEvent.click(screen.getByRole("button", { name: "Discover tools" }));
    expect(await screen.findByText("This endpoint is unavailable.")).toBeTruthy();
    expect(screen.queryByText("hidden-http-detail")).toBeNull();
    cleanup();

    vi.stubGlobal(
      "fetch",
      vi.fn(async (url: string) => {
        if (String(url).endsWith("/auth/me")) return jsonResponse(200, meBody("user-a"));
        throw new TypeError("network down");
      }),
    );
    await renderMetadata();
    verifyPat();
    await screen.findByRole("button", { name: "Discover tools" });
    fireEvent.click(screen.getByRole("button", { name: "Discover tools" }));
    expect(await screen.findByText("This endpoint is unavailable.")).toBeTruthy();
    expect(screen.queryByText("network down")).toBeNull();
  });

  it("treats a malformed or interrupted stream as a transport failure", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async (url: string) => {
        if (String(url).endsWith("/auth/me")) return jsonResponse(200, meBody("user-a"));
        return new Response("not-json", {
          status: 200,
          headers: { "Content-Type": "application/json" },
        });
      }),
    );
    await renderMetadata();
    verifyPat();
    await screen.findByRole("button", { name: "Discover tools" });
    fireEvent.click(screen.getByRole("button", { name: "Discover tools" }));
    expect(
      await screen.findByText(
        "The tool list response could not be read. That is not an empty catalog.",
      ),
    ).toBeTruthy();
    expect(
      screen.queryByText("This endpoint returned no tools. That is an empty catalog."),
    ).toBeNull();
    cleanup();

    vi.stubGlobal(
      "fetch",
      vi.fn(async (url: string) => {
        if (String(url).endsWith("/auth/me")) return jsonResponse(200, meBody("user-a"));
        return jsonResponse(200, toolMessage(999999, []));
      }),
    );
    await renderMetadata();
    verifyPat();
    await screen.findByRole("button", { name: "Discover tools" });
    fireEvent.click(screen.getByRole("button", { name: "Discover tools" }));
    expect(
      await screen.findByText(
        "The tool list response could not be read. That is not an empty catalog.",
      ),
    ).toBeTruthy();
    expect(
      screen.queryByText("This endpoint returned no tools. That is an empty catalog."),
    ).toBeNull();
    cleanup();

    vi.stubGlobal(
      "fetch",
      vi.fn(async (url: string) => {
        if (String(url).endsWith("/auth/me")) return jsonResponse(200, meBody("user-a"));
        const truncated =
          'event: message\ndata: {"jsonrpc":"2.0","id":1,"result":{"tools":[]}}';
        return new Response(truncated, {
          status: 200,
          headers: { "Content-Type": "text/event-stream" },
        });
      }),
    );
    await renderMetadata();
    verifyPat();
    await screen.findByRole("button", { name: "Discover tools" });
    fireEvent.click(screen.getByRole("button", { name: "Discover tools" }));
    expect(
      await screen.findByText(
        "The tool list response could not be read. That is not an empty catalog.",
      ),
    ).toBeTruthy();
    expect(
      screen.queryByText("This endpoint returned no tools. That is an empty catalog."),
    ).toBeNull();
    cleanup();

    vi.stubGlobal(
      "fetch",
      vi.fn(async (url: string) => {
        if (String(url).endsWith("/auth/me")) return jsonResponse(200, meBody("user-a"));
        const stream = new ReadableStream({
          start(controller) {
            controller.enqueue(
              new TextEncoder().encode(
                'event: message\ndata: {"jsonrpc":"2.0","id":1,"result":{"tools":[]}}',
              ),
            );
            controller.error(new Error("interrupted"));
          },
        });
        return new Response(stream, {
          status: 200,
          headers: { "Content-Type": "text/event-stream" },
        });
      }),
    );
    await renderMetadata();
    verifyPat();
    await screen.findByRole("button", { name: "Discover tools" });
    fireEvent.click(screen.getByRole("button", { name: "Discover tools" }));
    expect(
      await screen.findByText(
        "The tool list response could not be read. That is not an empty catalog.",
      ),
    ).toBeTruthy();
    expect(
      screen.queryByText("This endpoint returned no tools. That is an empty catalog."),
    ).toBeNull();
  });

  it("does not expire the Console session when tools/list is unauthenticated", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async (url: string) => {
        if (String(url).endsWith("/auth/me")) return jsonResponse(200, meBody("user-a"));
        return jsonResponse(
          401,
          {
            type: "urn:refraq:problem:AUTH_UNAUTHENTICATED",
            status: 401,
            detail: "Not signed in or session expired",
            code: "AUTH_UNAUTHENTICATED",
          },
          "application/problem+json",
        );
      }),
    );
    await renderMetadata();
    verifyPat();
    await screen.findByRole("button", { name: "Discover tools" });
    fireEvent.click(screen.getByRole("button", { name: "Discover tools" }));

    expect(await screen.findByText("This endpoint is unavailable.")).toBeTruthy();
    expect(screen.queryByText("Not signed in or session expired")).toBeNull();
    expect(document.body.textContent).not.toContain(PAT);
    expect(useSessionStore.getState().user?.id).toBe("user-a");
    expect(useSessionStore.getState().signedOutLocally).toBe(false);
    expect(window.location.pathname).toBe("/console/mcp/metadata");
  });

  it("shows a missing input schema instead of inventing one", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async (url: string, init?: RequestInit) => {
        if (String(url).endsWith("/auth/me")) return jsonResponse(200, meBody("user-a"));
        const id = requestId([url, init]);
        return jsonResponse(
          200,
          toolMessage(id, [
            {
              name: "bare_tool",
              description: "No schema was published.",
              execution: "read",
              annotations: { readOnlyHint: true },
              _meta: { "io.refraq/execution": "write" },
            },
          ]),
        );
      }),
    );
    await renderMetadata();
    verifyPat();
    await screen.findByRole("button", { name: "Discover tools" });
    fireEvent.click(screen.getByRole("button", { name: "Discover tools" }));

    const bare = await screen.findByRole("listitem", { name: "/mcp bare_tool" });
    expect(within(bare).getByText("No schema was published.")).toBeTruthy();
    expect(within(bare).getByText("Input schema is not published.")).toBeTruthy();
    expect(within(bare).getByText("write")).toBeTruthy();
    expect(within(bare).queryByText("read")).toBeNull();
    expect(within(bare).queryByText("{}")).toBeNull();
  });

  it("clears discovered tools when the User PAT changes and drops a late response", async () => {
    let release: (response: Response) => void = () => {};
    let holdNextList = false;
    vi.stubGlobal(
      "fetch",
      vi.fn(async (url: string, init?: RequestInit) => {
        if (String(url).endsWith("/auth/me")) return jsonResponse(200, meBody("user-a"));
        const id = requestId([url, init]);
        if (!holdNextList) return jsonResponse(200, metadataTools(id));
        return new Promise<Response>((resolve) => {
          release = resolve;
        });
      }),
    );
    await renderMetadata();
    verifyPat();
    await screen.findByRole("button", { name: "Discover tools" });
    fireEvent.click(screen.getByRole("button", { name: "Discover tools" }));
    expect(await screen.findByRole("listitem", { name: "/mcp run_sql" })).toBeTruthy();

    holdNextList = true;
    fireEvent.click(screen.getByRole("button", { name: "Discover tools" }));
    fireEvent.change(screen.getByLabelText("User PAT"), {
      target: { value: `${PAT}-edited` },
    });
    expect(screen.queryByRole("listitem", { name: "/mcp run_sql" })).toBeNull();
    expect(screen.queryByText("Run controlled SQL.")).toBeNull();
    expect(screen.queryByRole("button", { name: "Discover tools" })).toBeNull();

    await act(async () => {
      release(jsonResponse(200, metadataTools(1)));
    });
    expect(screen.queryByRole("listitem", { name: "/mcp run_sql" })).toBeNull();
    expect(screen.queryByText("Run controlled SQL.")).toBeNull();
    expect((screen.getByLabelText("User PAT") as HTMLInputElement).value).toBe(`${PAT}-edited`);
  });

  it("drops discovered tools when a persisted page show clears the User PAT", async () => {
    await renderMetadata();
    verifyPat();
    await screen.findByRole("button", { name: "Discover tools" });
    fireEvent.click(screen.getByRole("button", { name: "Discover tools" }));
    expect(await screen.findByRole("listitem", { name: "/mcp run_sql" })).toBeTruthy();

    act(() => {
      window.dispatchEvent(new PageTransitionEvent("pageshow", { persisted: false }));
    });
    expect(screen.getByRole("listitem", { name: "/mcp run_sql" })).toBeTruthy();

    act(() => {
      window.dispatchEvent(new PageTransitionEvent("pageshow", { persisted: true }));
    });
    expect((screen.getByLabelText("User PAT") as HTMLInputElement).value).toBe("");
    expect(screen.queryByRole("listitem", { name: "/mcp run_sql" })).toBeNull();
    expect(screen.queryByText("Run controlled SQL.")).toBeNull();
    expect(screen.queryByRole("button", { name: "Discover tools" })).toBeNull();
    expect(document.body.textContent).not.toContain(PAT);
  });

  it("does not offer discovery for a rejected User PAT", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async (url: string) => {
        if (String(url).endsWith("/auth/me")) return jsonResponse(200, meBody("user-b"));
        return jsonResponse(200, metadataTools(1));
      }),
    );
    await renderMetadata();
    verifyPat();
    expect(await screen.findByText("This User PAT belongs to a different user.")).toBeTruthy();
    expect(screen.queryByRole("button", { name: "Discover tools" })).toBeNull();
    expect(toolsListCalls()).toHaveLength(0);
  });
});
