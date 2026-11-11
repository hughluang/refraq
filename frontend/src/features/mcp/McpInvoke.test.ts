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
  matchResourceFromRoute: () => ({ found: false }),
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

const PAT = "rfqpat-distinct-secret-06";
const ORIGIN = "https://console.example.com";
const HTTP_FAILURE = "The call failed in HTTP or the proxy, before a tool result.";
const TRANSPORT_FAILURE = "The call response could not be read.";
const PROTOCOL_ERROR = "The call returned a protocol error.";
const SDK_ERROR = "The tool returned an error.";
const DOMAIN_ERROR = "The tool returned a domain error.";

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

const runSqlSchema = {
  type: "object",
  additionalProperties: false,
  required: ["statement"],
  properties: {
    statement: { type: "string", minLength: 1, maxLength: 40, pattern: "\\S" },
    limit: { type: "integer", minimum: 1, maximum: 100 },
    mode: { enum: ["plan", "run"] },
    note: { type: ["string", "null"] },
    tags: {
      type: "array",
      items: { type: "string" },
      minItems: 1,
      maxItems: 2,
    },
  },
};

function listedTools() {
  return [
    {
      name: "run_sql",
      description: "Run controlled SQL.",
      inputSchema: runSqlSchema,
      outputSchema: {
        title: "WrappedString",
        type: "object",
        properties: { result: { type: "string" } },
      },
      annotations: { readOnlyHint: true },
      execution: "write",
      _meta: { "io.refraq/execution": "read" },
    },
    {
      name: "set_object_semantics",
      description: "Write object semantics.",
      inputSchema: { type: "object", properties: { object_id: { type: "string" } } },
      annotations: { readOnlyHint: false },
      _meta: { "io.refraq/execution": "write" },
    },
    {
      name: "search_sources",
      description: "Find sources.",
      inputSchema: { type: "object", properties: { keywords: { type: "string" } } },
      annotations: { readOnlyHint: true },
      _meta: { "io.refraq/execution": "lookup" },
    },
    {
      name: "hint_only",
      description: "Hint without a class.",
      inputSchema: { type: "object" },
      annotations: { readOnlyHint: true },
    },
    {
      name: "blank_class",
      description: "Blank execution class.",
      inputSchema: { type: "object" },
      _meta: { "io.refraq/execution": "" },
    },
    {
      name: "get_object",
      description: "Top-level execution is not the class.",
      inputSchema: { type: "object" },
      execution: "read",
      annotations: { readOnlyHint: true },
    },
    {
      name: "bare_tool",
      description: "No schema was published.",
      annotations: { readOnlyHint: false },
      _meta: { "io.refraq/execution": "read" },
    },
    {
      name: "loose_tool",
      description: "Unknown schema keywords.",
      inputSchema: {
        type: "object",
        properties: { q: { type: "string", format: "date-time" } },
        if: { type: "object" },
        then: { required: ["missing"] },
      },
      _meta: { "io.refraq/execution": "read" },
    },
    {
      name: "count_rows",
      description: "Extra properties are numbers.",
      inputSchema: {
        type: "object",
        properties: { label: { type: "string" } },
        additionalProperties: { type: "number" },
      },
      _meta: { "io.refraq/execution": "read" },
    },
  ];
}

function entityTools() {
  return [
    {
      name: "validate_sql",
      description: "Check entity SQL.",
      inputSchema: {
        type: "object",
        properties: { query: { type: "string" } },
        required: ["query"],
      },
      annotations: { readOnlyHint: true },
      _meta: { "io.refraq/execution": "read" },
    },
    {
      name: "run_sql",
      description: "Run entity SQL.",
      inputSchema: {
        type: "object",
        properties: { query: { type: "string" } },
        required: ["query"],
      },
      annotations: { readOnlyHint: true },
      _meta: { "io.refraq/execution": "read" },
    },
  ];
}

function toolMessage(id: unknown, tools: unknown[]) {
  return { jsonrpc: "2.0", id, result: { tools } };
}

function callEnvelope(
  id: unknown,
  text: string,
  options?: { isError?: boolean; structured?: unknown; outputSchema?: boolean },
) {
  const structured = options?.structured === undefined ? text : options.structured;
  const result: Record<string, unknown> = {
    content: [{ type: "text", text }],
    isError: options?.isError ?? false,
  };
  if (structured !== undefined) result.structuredContent = { result: structured };
  if (options?.outputSchema !== false) {
    result.outputSchema = {
      title: "WrappedString",
      type: "object",
      properties: { result: { type: "string" } },
    };
  }
  return { jsonrpc: "2.0", id, result };
}

function domainText(code: string, message: string) {
  return JSON.stringify({ error: { code, message } });
}

type CallResponder = (
  url: string,
  body: { id?: unknown; params?: { name?: string; arguments?: unknown } },
  init: RequestInit | undefined,
) => Response | Promise<Response>;

let callResponder: CallResponder = (_url, body) =>
  jsonResponse(200, callEnvelope(body.id, JSON.stringify({ rows: [] })));

function installFetch() {
  vi.stubGlobal(
    "fetch",
    vi.fn(async (url: string, init?: RequestInit) => {
      if (String(url).endsWith("/auth/me")) return jsonResponse(200, meBody("user-a"));
      const body = typeof init?.body === "string" ? JSON.parse(init.body) : {};
      if (body.method === "tools/call") return callResponder(String(url), body, init);
      if (String(url) === `${ORIGIN}/mcp/entity`) return jsonResponse(200, toolMessage(body.id, entityTools()));
      return jsonResponse(200, toolMessage(body.id, listedTools()));
    }),
  );
}

function callPosts() {
  return vi.mocked(fetch).mock.calls.filter((call) => {
    const init = call[1] as RequestInit | undefined;
    return new Headers(init?.headers).get("mcp-method") === "tools/call";
  });
}

function verifyPat() {
  fireEvent.change(screen.getByLabelText("Personal access token"), { target: { value: PAT } });
  fireEvent.click(screen.getByRole("button", { name: "Verify personal access token" }));
}

async function renderMetadata() {
  const { default: Layout } = await import("@/app/console/mcp/layout");
  const { McpMetadataDetail } = await import("@/features/mcp/McpMetadataDetail");
  return render(shell(createElement(Layout, null, createElement(McpMetadataDetail))));
}

async function discover() {
  fireEvent.click(screen.getByRole("button", { name: "Discover tools" }));
  expect(await screen.findByRole("listitem", { name: "/mcp run_sql" })).toBeTruthy();
}

async function selectTool(qualified: string) {
  fireEvent.click(screen.getByRole("button", { name: `Select ${qualified}` }));
  return screen.findByRole("region", { name: `Arguments for ${qualified}` });
}

function editor() {
  return screen.getByRole("textbox", { name: "Arguments" }) as HTMLTextAreaElement;
}

function typeArguments(value: string) {
  fireEvent.change(editor(), { target: { value } });
}

function run(qualified: string) {
  fireEvent.click(screen.getByRole("button", { name: `Run ${qualified}` }));
}

describe("MCP explicit read invocation", () => {
  beforeEach(() => {
    stubDomApis();
    localStorage.clear();
    sessionStorage.clear();
    pathname.current = "/console/mcp/metadata";
    resetSessionStoreForTests();
    useSessionStore.setState({ user: sessionUser("user-a"), permissionsReady: true });
    api.mockReset();
    api.mockResolvedValue({ tools: [] });
    callResponder = (_url, body) => jsonResponse(200, callEnvelope(body.id, JSON.stringify({ rows: [] })));
    installFetch();
  });

  afterEach(() => {
    cleanup();
    resetSessionStoreForTests();
    vi.unstubAllGlobals();
    vi.restoreAllMocks();
  });

  it("shows a selected tool schema in an empty JSON editor without calling it", async () => {
    await renderMetadata();
    expect(callPosts()).toHaveLength(0);

    verifyPat();
    expect(await screen.findByText("This personal access token belongs to the signed-in user. user-a")).toBeTruthy();
    expect(callPosts()).toHaveLength(0);
    expect(screen.queryByRole("button", { name: /^Select / })).toBeNull();

    await discover();
    expect(callPosts()).toHaveLength(0);
    expect(screen.queryByRole("textbox", { name: "Arguments" })).toBeNull();
    expect(screen.queryByText("WrappedString")).toBeNull();

    const panel = await selectTool("/mcp run_sql");
    expect(within(panel).queryByText(/"statement"/)).toBeNull();
    fireEvent.click(within(panel).getByText("Input schema"));
    expect(within(panel).getByText(/"statement"/)).toBeTruthy();
    expect(within(panel).getByText(/"minLength"/)).toBeTruthy();
    expect(within(panel).queryByRole("textbox", { name: "statement" })).toBeNull();
    expect(within(panel).queryByLabelText("statement")).toBeNull();
    expect(within(panel).queryByLabelText("limit")).toBeNull();
    expect(editor().value).toBe("");
    expect(editor().value).not.toBe("{}");
    expect(callPosts()).toHaveLength(0);
    expect(screen.queryByRole("dialog")).toBeNull();
    expect(screen.queryByRole("button", { name: /download|export/i })).toBeNull();
  });

  it("blocks empty text, invalid JSON, and schema violations before dispatch", async () => {
    await renderMetadata();
    verifyPat();
    await screen.findByRole("button", { name: "Discover tools" });
    await discover();
    await selectTool("/mcp run_sql");

    run("/mcp run_sql");
    expect(screen.getByText("Arguments are empty.")).toBeTruthy();
    expect(editor().getAttribute("aria-invalid")).toBe("true");
    const errorId = screen.getByText("Arguments are empty.").closest(".mantine-InputWrapper-error")?.id;
    expect(editor().getAttribute("aria-describedby")).toContain(errorId);
    expect(callPosts()).toHaveLength(0);

    typeArguments("   ");
    run("/mcp run_sql");
    expect(screen.getByText("Arguments are empty.")).toBeTruthy();
    expect(editor().value).toBe("   ");
    expect(callPosts()).toHaveLength(0);

    typeArguments("{");
    run("/mcp run_sql");
    expect(screen.getByText(/Arguments are not valid JSON\./)).toBeTruthy();
    expect(document.body.textContent).toMatch(/position 1/);
    expect(callPosts()).toHaveLength(0);

    const cases: Array<{ value: string; reason: RegExp }> = [
      { value: '"select 1"', reason: /arguments must be object/ },
      { value: "{}", reason: /arguments\.statement is required/ },
      { value: '{"statement":1}', reason: /arguments\.statement must be string/ },
      { value: '{"statement":""}', reason: /arguments\.statement must be at least this many characters: 1/ },
      { value: '{"statement":"   "}', reason: /arguments\.statement must match \\S/ },
      {
        value: '{"statement":"this statement is definitely longer than forty"}',
        reason: /arguments\.statement must be at most this many characters: 40/,
      },
      { value: '{"statement":"select 1","limit":0}', reason: /arguments\.limit must be at least 1/ },
      { value: '{"statement":"select 1","limit":101}', reason: /arguments\.limit must be at most 100/ },
      { value: '{"statement":"select 1","limit":1.5}', reason: /arguments\.limit must be integer/ },
      { value: '{"statement":"select 1","mode":"nope"}', reason: /arguments\.mode must be one of \["plan","run"\]/ },
      { value: '{"statement":"select 1","note":1}', reason: /arguments\.note must be string or null/ },
      { value: '{"statement":"select 1","tags":[]}', reason: /arguments\.tags must contain at least this many items: 1/ },
      {
        value: '{"statement":"select 1","tags":["a","b","c"]}',
        reason: /arguments\.tags must contain at most this many items: 2/,
      },
      { value: '{"statement":"select 1","tags":[1]}', reason: /arguments\.tags\.0 must be string/ },
      { value: '{"statement":"select 1","extra":true}', reason: /arguments\.extra is not allowed/ },
    ];
    for (const item of cases) {
      typeArguments(item.value);
      run("/mcp run_sql");
      expect(screen.getByText(item.reason)).toBeTruthy();
      expect(callPosts()).toHaveLength(0);
    }

    await selectTool("/mcp count_rows");
    expect(editor().value).toBe("");
    typeArguments('{"label":"a","n":"x"}');
    run("/mcp count_rows");
    expect(screen.getByText(/arguments\.n must be number/)).toBeTruthy();
    expect(callPosts()).toHaveLength(0);
    expect(document.body.textContent).not.toMatch(/will succeed/i);
  });

  it("sends one tools/call for a read tool and withholds every other class", async () => {
    let release: (response: Response) => void = () => {};
    let captured: { url: string; init: RequestInit; body: Record<string, unknown> } | null = null;
    callResponder = (url, body, init) => {
      captured = { url, init: init ?? {}, body: body as Record<string, unknown> };
      return new Promise<Response>((resolve) => {
        release = resolve;
      });
    };
    await renderMetadata();
    verifyPat();
    await screen.findByRole("button", { name: "Discover tools" });
    await discover();

    const unknownTool = screen.getByRole("listitem", { name: "/mcp search_sources" });
    expect(within(unknownTool).getByText("Execution class is not published.")).toBeTruthy();
    expect(document.body.textContent).not.toContain("mcp.execution.lookup");
    for (const name of [
      "/mcp search_sources",
      "/mcp hint_only",
      "/mcp blank_class",
      "/mcp get_object",
    ]) {
      await selectTool(name);
      expect(screen.queryByRole("button", { name: /^Run / })).toBeNull();
      expect(screen.queryByRole("dialog")).toBeNull();
    }
    expect(callPosts()).toHaveLength(0);

    await selectTool("/mcp set_object_semantics");
    typeArguments('{"object_id":"held-write"}');
    run("/mcp set_object_semantics");
    expect(callPosts()).toHaveLength(0);
    expect(screen.getByRole("dialog")).toBeTruthy();
    expect(screen.getByRole("dialog").textContent).not.toContain(PAT);

    await selectTool("/mcp run_sql");
    expect(screen.getByRole("button", { name: "Run /mcp run_sql" })).toBeTruthy();
    typeArguments('{"statement":"select 1","limit":1}');
    expect(callPosts()).toHaveLength(0);
    expect(document.body.textContent).not.toMatch(/will succeed/i);

    run("/mcp run_sql");
    expect(callPosts()).toHaveLength(1);
    expect(captured).toBeTruthy();
    expect(captured?.url).toBe(`${ORIGIN}/mcp`);
    const init = captured?.init as RequestInit;
    expect(init.method).toBe("POST");
    expect(init.credentials).toBe("omit");
    const headers = new Headers(init.headers);
    expect(headers.get("Authorization")).toBe(`Bearer ${PAT}`);
    expect(headers.get("Content-Type")).toBe("application/json");
    expect(headers.get("Accept")).toContain("application/json");
    expect(headers.get("Accept")).toContain("text/event-stream");
    expect(headers.get("mcp-protocol-version")).toBe("2026-07-28");
    expect(headers.get("mcp-method")).toBe("tools/call");
    expect(headers.get("mcp-name")).toBe("run_sql");
    expect(headers.has("Mcp-Session-Id")).toBe(false);
    const payload = captured?.body as {
      jsonrpc: string;
      id: unknown;
      method: string;
      params: { name: string; arguments: unknown; _meta: Record<string, unknown> };
    };
    expect(payload.jsonrpc).toBe("2.0");
    expect(payload.method).toBe("tools/call");
    expect(payload.params.name).toBe("run_sql");
    expect(payload.params.arguments).toEqual({ statement: "select 1", limit: 1 });
    expect(payload.params._meta["io.modelcontextprotocol/protocolVersion"]).toBe("2026-07-28");
    expect(payload.params._meta["io.modelcontextprotocol/clientCapabilities"]).toEqual({});
    expect(typeof payload.id).toBe("number");
    const methods = vi
      .mocked(fetch)
      .mock.calls.map((call) => {
        const body = (call[1] as RequestInit | undefined)?.body;
        return typeof body === "string" ? body : "";
      })
      .join("\n");
    expect(methods).not.toContain("initialize");
    expect(api.mock.calls.some((call) => String(call[0]).includes("tools/call"))).toBe(false);

    typeArguments('{"statement":"select 2","limit":1}');
    expect(payload.params.arguments).toEqual({ statement: "select 1", limit: 1 });

    const marker = "snapshot-result-marker";
    await act(async () => {
      release(jsonResponse(200, callEnvelope(payload.id, JSON.stringify({ rows: [marker] }))));
    });
    expect(await screen.findByRole("region", { name: "Decoded JSON" })).toBeTruthy();
    expect(document.body.textContent).toContain(marker);
    expect(callPosts()).toHaveLength(1);
    expect(screen.queryByRole("dialog")).toBeNull();
  });

  it("shows a later server rejection and does not promise that local JSON will run", async () => {
    callResponder = (_url, body) => {
      const name = body.params?.name;
      if (name === "loose_tool") {
        return jsonResponse(
          200,
          callEnvelope(body.id, domainText("QUERY_REJECTED", "statement is not allowed")),
        );
      }
      return jsonResponse(200, callEnvelope(body.id, domainText("BARE_REJECTED", "server remains authority")));
    };
    await renderMetadata();
    verifyPat();
    await screen.findByRole("button", { name: "Discover tools" });
    await discover();

    await selectTool("/mcp loose_tool");
    typeArguments('{"q":"yesterday"}');
    expect(document.body.textContent).not.toMatch(/will succeed/i);
    run("/mcp loose_tool");
    expect(await screen.findByRole("region", { name: DOMAIN_ERROR })).toBeTruthy();
    expect(document.body.textContent).toContain("QUERY_REJECTED");
    expect(document.body.textContent).toContain("statement is not allowed");
    expect(document.body.textContent).not.toMatch(/will succeed/i);
    expect(callPosts()).toHaveLength(1);
    const loose = JSON.parse(String((callPosts()[0][1] as RequestInit).body)) as {
      params: { arguments: unknown };
    };
    expect(loose.params.arguments).toEqual({ q: "yesterday" });

    await selectTool("/mcp bare_tool");
    const panel = screen.getByRole("region", { name: "Arguments for /mcp bare_tool" });
    fireEvent.click(within(panel).getByText("Input schema"));
    expect(within(panel).getByText("Input schema is not published.")).toBeTruthy();
    expect(within(panel).queryByText("{}")).toBeNull();
    expect(editor().value).toBe("");
    expect(document.body.textContent).not.toContain("QUERY_REJECTED");
    typeArguments('{"z":true}');
    run("/mcp bare_tool");
    expect((await screen.findByRole("region", { name: DOMAIN_ERROR })).textContent).toContain("BARE_REJECTED");
    expect(document.body.textContent).toContain("server remains authority");
    expect(callPosts()).toHaveLength(2);
    const bare = JSON.parse(String((callPosts()[1][1] as RequestInit).body)) as {
      params: { name: string; arguments: unknown };
    };
    expect(bare.params.name).toBe("bare_tool");
    expect(bare.params.arguments).toEqual({ z: true });
  });

  it("keeps the sent arguments on the result when a later edit fails validation", async () => {
    callResponder = (_url, body) =>
      jsonResponse(200, callEnvelope(body.id, JSON.stringify({ rows: ["snap-marker"] })));
    await renderMetadata();
    verifyPat();
    await screen.findByRole("button", { name: "Discover tools" });
    await discover();
    await selectTool("/mcp run_sql");
    typeArguments('{"statement":"select 1"}');
    run("/mcp run_sql");

    const result = await screen.findByRole("region", { name: "Tool result" });
    expect(result.textContent).toContain("snap-marker");
    expect(within(result).getByText('{"statement":"select 1"}')).toBeTruthy();

    typeArguments("{");
    run("/mcp run_sql");
    expect(screen.getByText(/Arguments are not valid JSON\./)).toBeTruthy();
    expect(editor().value).toBe("{");
    expect(within(result).getByText('{"statement":"select 1"}')).toBeTruthy();
    expect(result.textContent).not.toContain("position 1");
    expect(callPosts()).toHaveLength(1);
  });

  it("offers decoded JSON and the protocol payload without drawing outputSchema as the business object", async () => {
    const text = JSON.stringify({ columns: ["id"], rows: [{ id: "row-1" }] });
    callResponder = (_url, body) => jsonResponse(200, callEnvelope(body.id, text));
    await renderMetadata();
    verifyPat();
    await screen.findByRole("button", { name: "Discover tools" });
    await discover();
    await selectTool("/mcp run_sql");
    typeArguments('{"statement":"select 1"}');
    run("/mcp run_sql");

    const result = await screen.findByRole("region", { name: "Tool result" });
    expect(result.style.overflow).toBe("auto");
    expect(result.style.maxHeight).not.toBe("");
    const decoded = screen.getByRole("region", { name: "Decoded JSON" });
    expect(decoded.textContent).toContain("row-1");
    expect(decoded.textContent).toContain('"rows"');
    expect(decoded.textContent).not.toContain("outputSchema");
    expect(decoded.textContent).not.toContain("WrappedString");
    const raw = screen.getByRole("region", { name: "Protocol payload" });
    expect(raw.textContent).toContain("outputSchema");
    expect(raw.textContent).toContain("WrappedString");
    expect(raw.textContent).toContain("row-1");
    expect(screen.queryByRole("button", { name: /download|export/i })).toBeNull();
    expect(document.querySelector("a[download]")).toBeNull();
    expect(screen.queryByRole("region", { name: DOMAIN_ERROR })).toBeNull();
    expect(screen.queryByRole("region", { name: SDK_ERROR })).toBeNull();
  });

  it("keeps plain text, empty data, masks, and withheld cells as the server wrote them", async () => {
    const payloads = [
      "not json at all",
      JSON.stringify({ columns: [], rows: [] }),
      JSON.stringify({
        columns: ["name", "salary"],
        rows: [["ada", null]],
        masks: { salary: "***" },
        __withheld: ["salary"],
        truncated: true,
      }),
    ];
    let step = 0;
    callResponder = (_url, body) => jsonResponse(200, callEnvelope(body.id, payloads[step] ?? payloads[0]));
    await renderMetadata();
    verifyPat();
    await screen.findByRole("button", { name: "Discover tools" });
    await discover();
    await selectTool("/mcp run_sql");
    typeArguments('{"statement":"select 1"}');

    run("/mcp run_sql");
    const text = await screen.findByRole("region", { name: "Tool text" });
    expect(text.textContent).toContain("not json at all");
    expect(screen.queryByRole("region", { name: "Decoded JSON" })).toBeNull();
    expect(document.body.textContent).not.toMatch(/not valid JSON|parse error|Unexpected token/i);
    expect(screen.getByRole("region", { name: "Protocol payload" }).textContent).toContain("not json at all");

    step = 1;
    run("/mcp run_sql");
    const empty = await screen.findByRole("region", { name: "Decoded JSON" });
    expect(empty.textContent).toContain('"rows"');
    expect(empty.textContent).toContain("[]");
    expect(empty.textContent).not.toMatch(/total/i);
    expect(screen.getByRole("region", { name: "Tool result" })).toBeTruthy();
    expect(screen.queryByRole("region", { name: HTTP_FAILURE })).toBeNull();
    expect(screen.queryByRole("region", { name: DOMAIN_ERROR })).toBeNull();
    expect(screen.queryByRole("region", { name: SDK_ERROR })).toBeNull();
    expect(screen.queryByRole("region", { name: PROTOCOL_ERROR })).toBeNull();

    step = 2;
    run("/mcp run_sql");
    const withheld = await screen.findByRole("region", { name: "Decoded JSON" });
    expect(withheld.textContent).toContain("__withheld");
    expect(withheld.textContent).toContain("***");
    expect(withheld.textContent).toContain("truncated");
    expect(withheld.textContent).not.toMatch(/total/i);
    expect(screen.getByRole("region", { name: "Protocol payload" }).textContent).toContain("__withheld");
  });

  it("distinguishes HTTP, protocol, SDK, and domain failures", async () => {
    const cases: Array<{
      respond: CallResponder;
      region: string;
      absent: string[];
      present: string[];
      missing: string[];
    }> = [
      {
        respond: (_url, body) =>
          jsonResponse(500, callEnvelope(body.id, JSON.stringify({ rows: ["http-success-marker"] }))),
        region: HTTP_FAILURE,
        absent: ["Tool result", TRANSPORT_FAILURE, PROTOCOL_ERROR],
        present: [],
        missing: ["http-success-marker"],
      },
      {
        respond: () =>
          jsonResponse(502, { error: "mcp_upstream_unavailable", rows: ["proxy-marker"] }),
        region: HTTP_FAILURE,
        absent: ["Tool result", TRANSPORT_FAILURE, PROTOCOL_ERROR],
        present: [],
        missing: ["mcp_upstream_unavailable", "proxy-marker"],
      },
      {
        respond: () =>
          jsonResponse(
            403,
            {
              type: "urn:refraq:problem:FORBIDDEN",
              title: "Forbidden",
              status: 403,
              detail: "problem-detail-marker",
            },
            "application/problem+json",
          ),
        region: HTTP_FAILURE,
        absent: ["Tool result", PROTOCOL_ERROR],
        present: [],
        missing: ["problem-detail-marker"],
      },
      {
        respond: (_url, body) =>
          jsonResponse(400, {
            jsonrpc: "2.0",
            id: body.id,
            error: { code: -32602, message: "Invalid params" },
          }),
        region: PROTOCOL_ERROR,
        absent: [HTTP_FAILURE, "Tool result", DOMAIN_ERROR, SDK_ERROR],
        present: ["-32602", "Invalid params"],
        missing: [],
      },
      {
        respond: (_url, body) =>
          jsonResponse(200, callEnvelope(body.id, "Field required: sql", { isError: true, outputSchema: false })),
        region: SDK_ERROR,
        absent: [DOMAIN_ERROR, "Tool result", HTTP_FAILURE],
        present: ["Field required: sql"],
        missing: [],
      },
      {
        respond: (_url, body) =>
          jsonResponse(
            200,
            callEnvelope(body.id, domainText("SOURCE_NOT_FOUND", "No source"), { isError: true }),
          ),
        region: SDK_ERROR,
        absent: [DOMAIN_ERROR, "Tool result"],
        present: ["SOURCE_NOT_FOUND"],
        missing: [],
      },
      {
        respond: (_url, body) =>
          jsonResponse(200, callEnvelope(body.id, domainText("SOURCE_NOT_FOUND", "No source"))),
        region: DOMAIN_ERROR,
        absent: ["Tool result", SDK_ERROR, HTTP_FAILURE],
        present: ["SOURCE_NOT_FOUND", "No source"],
        missing: [],
      },
      {
        respond: (_url, body) =>
          jsonResponse(
            200,
            callEnvelope(body.id, "see structured", {
              structured: domainText("GRANT_MISSING", "no grant"),
            }),
          ),
        region: DOMAIN_ERROR,
        absent: ["Tool result", SDK_ERROR],
        present: ["GRANT_MISSING", "no grant", "see structured"],
        missing: [],
      },
    ];

    await renderMetadata();
    verifyPat();
    await screen.findByRole("button", { name: "Discover tools" });
    await discover();
    await selectTool("/mcp run_sql");
    typeArguments('{"statement":"select 1"}');

    for (const item of cases) {
      callResponder = item.respond;
      const before = callPosts().length;
      run("/mcp run_sql");
      expect(await screen.findByRole("region", { name: item.region })).toBeTruthy();
      for (const name of item.absent) {
        expect(screen.queryByRole("region", { name })).toBeNull();
      }
      for (const text of item.present) expect(document.body.textContent).toContain(text);
      for (const text of item.missing) expect(document.body.textContent).not.toContain(text);
      expect(callPosts()).toHaveLength(before + 1);
    }
  });

  it("treats a broken stream as a transport failure and does not retry", async () => {
    let mode: "sse" | "cut" | "interrupted" | "mismatch" | "garbage" = "sse";
    callResponder = (_url, body) => {
      if (mode === "sse") {
        const payload = `event: message\ndata: ${JSON.stringify(callEnvelope(body.id, JSON.stringify({ rows: ["sse-row"] })))}\n\n`;
        return new Response(payload, { status: 200, headers: { "Content-Type": "text/event-stream" } });
      }
      if (mode === "cut") {
        const payload = `event: message\ndata: ${JSON.stringify(callEnvelope(body.id, JSON.stringify({ rows: ["sse-cut-marker"] })))}`;
        return new Response(payload, { status: 200, headers: { "Content-Type": "text/event-stream" } });
      }
      if (mode === "interrupted") {
        const stream = new ReadableStream({
          start(controller) {
            controller.enqueue(
              new TextEncoder().encode(
                `event: message\ndata: ${JSON.stringify(callEnvelope(body.id, JSON.stringify({ rows: ["sse-cut-marker"] })))}\n\n`,
              ),
            );
            controller.error(new Error("interrupted"));
          },
        });
        return new Response(stream, { status: 200, headers: { "Content-Type": "text/event-stream" } });
      }
      if (mode === "mismatch") {
        return jsonResponse(200, callEnvelope(999999, JSON.stringify({ rows: ["wrong-id-marker"] })));
      }
      return new Response("not-json", { status: 200, headers: { "Content-Type": "application/json" } });
    };

    await renderMetadata();
    verifyPat();
    await screen.findByRole("button", { name: "Discover tools" });
    await discover();
    await selectTool("/mcp run_sql");
    typeArguments('{"statement":"select 1"}');

    run("/mcp run_sql");
    expect((await screen.findByRole("region", { name: "Decoded JSON" })).textContent).toContain("sse-row");
    expect(callPosts()).toHaveLength(1);

    mode = "cut";
    run("/mcp run_sql");
    expect(await screen.findByRole("region", { name: TRANSPORT_FAILURE })).toBeTruthy();
    expect(document.body.textContent).not.toContain("sse-cut-marker");
    expect(screen.queryByRole("region", { name: "Tool result" })).toBeNull();
    expect(callPosts()).toHaveLength(2);
    await act(async () => {
      await new Promise((resolve) => setTimeout(resolve, 0));
    });
    expect(callPosts()).toHaveLength(2);

    mode = "interrupted";
    run("/mcp run_sql");
    expect(await screen.findByRole("region", { name: TRANSPORT_FAILURE })).toBeTruthy();
    expect(document.body.textContent).not.toContain("sse-cut-marker");
    expect(callPosts()).toHaveLength(3);

    mode = "mismatch";
    run("/mcp run_sql");
    expect(await screen.findByRole("region", { name: TRANSPORT_FAILURE })).toBeTruthy();
    expect(document.body.textContent).not.toContain("wrong-id-marker");
    expect(callPosts()).toHaveLength(4);

    mode = "garbage";
    run("/mcp run_sql");
    expect(await screen.findByRole("region", { name: TRANSPORT_FAILURE })).toBeTruthy();
    expect(screen.queryByRole("region", { name: HTTP_FAILURE })).toBeNull();
    expect(callPosts()).toHaveLength(5);
  });

  it("does not store arguments or results, and a 401 does not log the Console session out", async () => {
    const writes: string[] = [];
    const original = Storage.prototype.setItem;
    vi.spyOn(Storage.prototype, "setItem").mockImplementation(function (
      this: Storage,
      key: string,
      value: string,
    ) {
      writes.push(`${key}=${value}`);
      return original.call(this, key, value);
    });
    const opens = vi.fn();
    vi.stubGlobal("indexedDB", { open: opens });
    const marker = "unique-result-marker-06";
    let unauthenticated = false;
    callResponder = (_url, body) => {
      if (unauthenticated) {
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
      }
      return jsonResponse(200, callEnvelope(body.id, JSON.stringify({ rows: [marker] })));
    };

    await renderMetadata();
    verifyPat();
    await screen.findByRole("button", { name: "Discover tools" });
    await discover();
    await selectTool("/mcp run_sql");
    typeArguments('{"statement":"unique-statement-06"}');
    run("/mcp run_sql");
    expect((await screen.findByRole("region", { name: "Tool result" })).textContent).toContain(
      "unique-result-marker-06",
    );

    const stored = writes.join("\n");
    expect(stored).not.toContain("unique-statement-06");
    expect(stored).not.toContain(marker);
    expect(stored).not.toContain(PAT);
    expect(window.location.href).toBe("https://console.example.com/console/mcp/metadata");
    expect(window.location.search).toBe("");
    expect(opens).not.toHaveBeenCalled();
    expect(document.querySelector("a[download]")).toBeNull();

    unauthenticated = true;
    run("/mcp run_sql");
    expect(
      await screen.findByText(
        "That personal access token was not accepted. The Console session stays signed in.",
      ),
    ).toBeTruthy();
    expect(screen.queryByRole("region", { name: HTTP_FAILURE })).toBeNull();
    expect(screen.queryByRole("region", { name: "Tool result" })).toBeNull();
    expect(document.body.textContent).not.toContain("Not signed in or session expired");
    expect(useSessionStore.getState().user?.id).toBe("user-a");
    expect(useSessionStore.getState().signedOutLocally).toBe(false);
    expect(window.location.pathname).toBe("/console/mcp/metadata");
    expect(callPosts()).toHaveLength(2);
  });

  it("clears arguments and results when the endpoint, tool, or User PAT changes", async () => {
    let release: (response: Response) => void = () => {};
    let hold = false;
    callResponder = (_url, body) => {
      if (!hold) return jsonResponse(200, callEnvelope(body.id, JSON.stringify({ rows: ["kept-marker"] })));
      return new Promise<Response>((resolve) => {
        release = resolve;
      });
    };
    const view = await renderMetadata();
    verifyPat();
    await screen.findByRole("button", { name: "Discover tools" });
    await discover();
    await selectTool("/mcp run_sql");
    typeArguments('{"statement":"select 1"}');
    run("/mcp run_sql");
    expect((await screen.findByRole("region", { name: "Tool result" })).textContent).toContain("kept-marker");

    await selectTool("/mcp bare_tool");
    expect(editor().value).toBe("");
    expect(document.body.textContent).not.toContain("kept-marker");

    await selectTool("/mcp run_sql");
    expect(editor().value).toBe("");
    typeArguments('{"statement":"select 1"}');
    hold = true;
    run("/mcp run_sql");
    expect(callPosts()).toHaveLength(2);

    pathname.current = "/console/mcp/entity";
    view.rerender(
      shell(
        createElement(
          (await import("@/app/console/mcp/layout")).default,
          null,
          createElement((await import("@/features/mcp/McpEntityDetail")).McpEntityDetail),
        ),
      ),
    );
    expect((screen.getByLabelText("Personal access token") as HTMLInputElement).value).toBe(PAT);
    expect(screen.getByText("This personal access token belongs to the signed-in user. user-a")).toBeTruthy();
    expect(screen.getByText("Selected endpoint /mcp/entity")).toBeTruthy();
    expect(screen.queryByRole("textbox", { name: "Arguments" })).toBeNull();
    expect(document.body.textContent).not.toContain("kept-marker");
    expect(document.body.textContent).not.toContain("late-endpoint-marker");

    await act(async () => {
      release(jsonResponse(200, callEnvelope(1, JSON.stringify({ rows: ["late-endpoint-marker"] }))));
    });
    expect(document.body.textContent).not.toContain("late-endpoint-marker");
    expect((screen.getByLabelText("Personal access token") as HTMLInputElement).value).toBe(PAT);

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
    expect(document.body.textContent).not.toContain("late-endpoint-marker");
    expect(screen.queryByRole("listitem", { name: "/mcp run_sql" })).toBeNull();
  });

  it("drops a late tools/call when the User PAT changes and when a persisted page is restored", async () => {
    let release: (response: Response) => void = () => {};
    let hold = false;
    callResponder = (_url, body) => {
      if (!hold) return jsonResponse(200, callEnvelope(body.id, JSON.stringify({ rows: ["pat-marker"] })));
      return new Promise<Response>((resolve) => {
        release = resolve;
      });
    };
    await renderMetadata();
    verifyPat();
    await screen.findByRole("button", { name: "Discover tools" });
    await discover();
    await selectTool("/mcp run_sql");
    typeArguments('{"statement":"select 1"}');
    run("/mcp run_sql");
    expect((await screen.findByRole("region", { name: "Tool result" })).textContent).toContain("pat-marker");

    act(() => {
      window.dispatchEvent(new PageTransitionEvent("pageshow", { persisted: false }));
    });
    expect(document.body.textContent).toContain("pat-marker");
    expect((screen.getByLabelText("Personal access token") as HTMLInputElement).value).toBe(PAT);

    hold = true;
    run("/mcp run_sql");
    fireEvent.change(screen.getByLabelText("Personal access token"), { target: { value: `${PAT}-edited` } });
    expect(screen.queryByRole("textbox", { name: "Arguments" })).toBeNull();
    expect(document.body.textContent).not.toContain("pat-marker");
    await act(async () => {
      release(jsonResponse(200, callEnvelope(1, JSON.stringify({ rows: ["late-pat-marker"] }))));
    });
    expect(document.body.textContent).not.toContain("late-pat-marker");
    expect((screen.getByLabelText("Personal access token") as HTMLInputElement).value).toBe(`${PAT}-edited`);

    fireEvent.change(screen.getByLabelText("Personal access token"), { target: { value: PAT } });
    verifyPat();
    expect(await screen.findByRole("button", { name: "Discover tools" })).toBeTruthy();
    await discover();
    await selectTool("/mcp run_sql");
    expect(editor().value).toBe("");
    expect(document.body.textContent).not.toContain("pat-marker");
    expect(document.body.textContent).not.toContain("late-pat-marker");

    hold = false;
    typeArguments('{"statement":"select 1"}');
    run("/mcp run_sql");
    expect((await screen.findByRole("region", { name: "Tool result" })).textContent).toContain("pat-marker");
    act(() => {
      window.dispatchEvent(new PageTransitionEvent("pageshow", { persisted: true }));
    });
    expect((screen.getByLabelText("Personal access token") as HTMLInputElement).value).toBe("");
    expect(document.body.textContent).not.toContain("pat-marker");
    expect(document.body.textContent).not.toContain(PAT);
    expect(screen.queryByRole("button", { name: "Discover tools" })).toBeNull();
  });

  it("keeps arguments and results when the same detail is opened again", async () => {
    callResponder = (_url, body) =>
      jsonResponse(200, callEnvelope(body.id, JSON.stringify({ rows: ["roundtrip-marker"] })));
    const view = await renderMetadata();
    verifyPat();
    await screen.findByRole("button", { name: "Discover tools" });
    await discover();
    await selectTool("/mcp run_sql");
    typeArguments('{"statement":"select 1"}');
    run("/mcp run_sql");
    expect((await screen.findByRole("region", { name: "Tool result" })).textContent).toContain(
      "roundtrip-marker",
    );
    const calls = callPosts().length;

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
    expect(document.body.textContent).not.toContain("roundtrip-marker");

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
    expect((await screen.findByRole("region", { name: "Tool result" })).textContent).toContain(
      "roundtrip-marker",
    );
    expect(editor().value).toBe('{"statement":"select 1"}');
    expect((screen.getByLabelText("Personal access token") as HTMLInputElement).value).toBe(PAT);
    expect(callPosts()).toHaveLength(calls);
    expect(screen.getByRole("listitem", { name: "/mcp run_sql" })).toBeTruthy();
  });

  it("qualifies the two run_sql tools by endpoint and keeps entity validate_sql distinct", async () => {
    const seen: Array<{ url: string; name: string; arguments: unknown }> = [];
    callResponder = (url, body) => {
      const name = body.params?.name ?? "";
      seen.push({ url, name, arguments: body.params?.arguments });
      const marker = name === "validate_sql" ? "validate-marker" : url.endsWith("/mcp/entity") ? "entity-sql-marker" : "metadata-sql-marker";
      return jsonResponse(200, callEnvelope(body.id, JSON.stringify({ rows: [marker] })));
    };
    const view = await renderMetadata();
    verifyPat();
    await screen.findByRole("button", { name: "Discover tools" });
    await discover();
    await selectTool("/mcp run_sql");
    typeArguments('{"statement":"select 1"}');
    run("/mcp run_sql");
    expect((await screen.findByRole("region", { name: "Tool result" })).textContent).toContain(
      "metadata-sql-marker",
    );
    expect(seen.at(-1)).toMatchObject({
      url: `${ORIGIN}/mcp`,
      name: "run_sql",
      arguments: { statement: "select 1" },
    });

    pathname.current = "/console/mcp/entity";
    view.rerender(
      shell(
        createElement(
          (await import("@/app/console/mcp/layout")).default,
          null,
          createElement((await import("@/features/mcp/McpEntityDetail")).McpEntityDetail),
        ),
      ),
    );
    expect(document.body.textContent).not.toContain("metadata-sql-marker");
    expect(screen.queryByRole("textbox", { name: "Arguments" })).toBeNull();
    expect((screen.getByLabelText("Personal access token") as HTMLInputElement).value).toBe(PAT);
    fireEvent.click(screen.getByRole("button", { name: "Discover tools" }));
    expect(await screen.findByRole("listitem", { name: "/mcp/entity validate_sql" })).toBeTruthy();
    expect(screen.getByRole("listitem", { name: "/mcp/entity run_sql" })).toBeTruthy();
    expect(screen.queryByRole("listitem", { name: "/mcp run_sql" })).toBeNull();

    await selectTool("/mcp/entity validate_sql");
    typeArguments('{"query":"select 1"}');
    run("/mcp/entity validate_sql");
    expect((await screen.findByRole("region", { name: "Tool result" })).textContent).toContain(
      "validate-marker",
    );
    expect(seen.at(-1)).toMatchObject({
      url: `${ORIGIN}/mcp/entity`,
      name: "validate_sql",
      arguments: { query: "select 1" },
    });

    await selectTool("/mcp/entity run_sql");
    expect(editor().value).toBe("");
    expect(document.body.textContent).not.toContain("validate-marker");
    typeArguments('{"query":"select 2"}');
    run("/mcp/entity run_sql");
    expect((await screen.findByRole("region", { name: "Tool result" })).textContent).toContain(
      "entity-sql-marker",
    );
    expect(document.body.textContent).not.toContain("validate-marker");
    expect(document.body.textContent).not.toContain("metadata-sql-marker");
    expect(seen.at(-1)).toMatchObject({
      url: `${ORIGIN}/mcp/entity`,
      name: "run_sql",
      arguments: { query: "select 2" },
    });
    expect(screen.queryByRole("button", { name: "Run /mcp/entity validate_sql" })).toBeNull();
    expect(screen.getByRole("button", { name: "Run /mcp/entity run_sql" })).toBeTruthy();
  });
});
