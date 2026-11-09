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

const PAT = "rfqpat-distinct-secret-07";
const ORIGIN = "https://console.example.com";
const NOTICE = "This confirmation is not an authorization grant. External MCP clients are unaffected.";
const ARGUMENTS = '{"object_id":"obj-7"}';

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

function semanticsCatalog(execution: string, description: string) {
  return metadataTools().map((tool) =>
    tool.name === "set_object_semantics"
      ? { ...tool, description, _meta: { "io.refraq/execution": execution } }
      : tool,
  );
}

function metadataTools() {
  return [
    {
      name: "set_object_semantics",
      description: "Write object semantics.",
      inputSchema: {
        type: "object",
        additionalProperties: false,
        required: ["object_id"],
        properties: { object_id: { type: "string", minLength: 1 } },
      },
      annotations: { readOnlyHint: false },
      _meta: { "io.refraq/execution": "write" },
    },
    {
      name: "upsert_join",
      description: "Write a join.",
      inputSchema: {
        type: "object",
        additionalProperties: false,
        required: ["left_id"],
        properties: { left_id: { type: "string", minLength: 1 } },
      },
      annotations: { readOnlyHint: true },
      _meta: { "io.refraq/execution": "write" },
    },
    {
      name: "set_column_semantics",
      description: "Named like a mutation but published as a read.",
      inputSchema: {
        type: "object",
        additionalProperties: false,
        required: ["object_id"],
        properties: { object_id: { type: "string", minLength: 1 } },
      },
      annotations: { readOnlyHint: false },
      _meta: { "io.refraq/execution": "read" },
    },
    {
      name: "run_sql",
      description: "Run controlled SQL.",
      inputSchema: {
        type: "object",
        additionalProperties: false,
        required: ["statement"],
        properties: { statement: { type: "string", minLength: 1 } },
      },
      annotations: { readOnlyHint: true },
      execution: "write",
      _meta: { "io.refraq/execution": "read" },
    },
    {
      name: "search_sources",
      description: "Find sources.",
      inputSchema: { type: "object" },
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
      name: "rename_object",
      description: "Some other execution class.",
      inputSchema: { type: "object" },
      _meta: { "io.refraq/execution": "mutation" },
    },
    {
      name: "get_object",
      description: "Top-level execution is not the class.",
      inputSchema: { type: "object" },
      execution: "read",
      annotations: { readOnlyHint: true },
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
        additionalProperties: false,
        required: ["query"],
        properties: { query: { type: "string", minLength: 1 } },
      },
      annotations: { readOnlyHint: true },
      _meta: { "io.refraq/execution": "read" },
    },
    {
      name: "run_sql",
      description: "Run entity SQL.",
      inputSchema: {
        type: "object",
        additionalProperties: false,
        required: ["query"],
        properties: { query: { type: "string", minLength: 1 } },
      },
      annotations: { readOnlyHint: true },
      _meta: { "io.refraq/execution": "read" },
    },
  ];
}

function toolMessage(id: unknown, tools: unknown[]) {
  return { jsonrpc: "2.0", id, result: { tools } };
}

function callEnvelope(id: unknown, text: string) {
  return {
    jsonrpc: "2.0",
    id,
    result: {
      content: [{ type: "text", text }],
      isError: false,
      structuredContent: { result: text },
    },
  };
}

type CallResponder = (
  url: string,
  body: { id?: unknown; params?: { name?: string; arguments?: unknown } },
  init: RequestInit | undefined,
) => Response | Promise<Response>;

let callResponder: CallResponder = (_url, body) =>
  jsonResponse(200, callEnvelope(body.id, JSON.stringify({ rows: ["write-result"] })));
let metadataOverride: unknown[] | null = null;
let metadataUnreadable = false;

function installFetch() {
  vi.stubGlobal(
    "fetch",
    vi.fn(async (url: string, init?: RequestInit) => {
      if (String(url).endsWith("/auth/me")) return jsonResponse(200, meBody("user-a"));
      const body = typeof init?.body === "string" ? JSON.parse(init.body) : {};
      if (body.method === "tools/call") return callResponder(String(url), body, init);
      if (String(url) === `${ORIGIN}/mcp/entity`) return jsonResponse(200, toolMessage(body.id, entityTools()));
      if (metadataUnreadable) return jsonResponse(200, { jsonrpc: "2.0", id: body.id, result: {} });
      return jsonResponse(200, toolMessage(body.id, metadataOverride ?? metadataTools()));
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
  fireEvent.change(screen.getByLabelText("User PAT"), { target: { value: PAT } });
  fireEvent.click(screen.getByRole("button", { name: "Verify User PAT" }));
}

async function renderMetadata() {
  const { default: Layout } = await import("@/app/console/mcp/layout");
  const { McpMetadataDetail } = await import("@/features/mcp/McpMetadataDetail");
  return render(shell(createElement(Layout, null, createElement(McpMetadataDetail))));
}

async function discover() {
  fireEvent.click(screen.getByRole("button", { name: "Discover tools" }));
  expect(await screen.findByRole("listitem", { name: "/mcp set_object_semantics" })).toBeTruthy();
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

function confirmWrite() {
  const dialog = screen.getByRole("dialog", { name: "Confirm this write" });
  fireEvent.click(within(dialog).getByRole("button", { name: "Confirm" }));
}

function cancelWrite() {
  const dialog = screen.getByRole("dialog", { name: "Confirm this write" });
  fireEvent.click(within(dialog).getByRole("button", { name: "Cancel" }));
}

function postedArguments(index = 0): unknown {
  const init = callPosts()[index][1] as RequestInit;
  const payload = JSON.parse(String(init.body)) as { params: { arguments: unknown } };
  return payload.params.arguments;
}

async function readyWrite() {
  const view = await renderMetadata();
  verifyPat();
  await screen.findByRole("button", { name: "Discover tools" });
  await discover();
  await selectTool("/mcp set_object_semantics");
  typeArguments(ARGUMENTS);
  return view;
}

describe("MCP metadata write confirmation", () => {
  beforeEach(() => {
    stubDomApis();
    localStorage.clear();
    sessionStorage.clear();
    pathname.current = "/console/mcp/metadata";
    resetSessionStoreForTests();
    useSessionStore.setState({ user: sessionUser("user-a"), permissionsReady: true });
    api.mockReset();
    api.mockResolvedValue({ tools: [] });
    callResponder = (_url, body) =>
      jsonResponse(200, callEnvelope(body.id, JSON.stringify({ rows: ["write-result"] })));
    metadataOverride = null;
    metadataUnreadable = false;
    installFetch();
  });

  afterEach(() => {
    cleanup();
    resetSessionStoreForTests();
    vi.unstubAllGlobals();
    vi.restoreAllMocks();
  });

  it("shows the exact write snapshot and dispatches that body only after confirm", async () => {
    await renderMetadata();
    verifyPat();
    expect(await screen.findByText("This User PAT belongs to the signed-in user. user-a")).toBeTruthy();
    await discover();
    await selectTool("/mcp set_object_semantics");
    expect(callPosts()).toHaveLength(0);
    expect(screen.queryByRole("dialog")).toBeNull();

    typeArguments(ARGUMENTS);
    expect(callPosts()).toHaveLength(0);
    expect(document.body.textContent).not.toMatch(/will succeed/i);

    run("/mcp set_object_semantics");
    const dialog = await screen.findByRole("dialog", { name: "Confirm this write" });
    expect(callPosts()).toHaveLength(0);
    expect(within(dialog).getByText(NOTICE)).toBeTruthy();
    expect(within(dialog).getByText("Endpoint /mcp")).toBeTruthy();
    expect(within(dialog).getByText("Verified user.id user-a")).toBeTruthy();
    expect(within(dialog).getByText("Tool set_object_semantics")).toBeTruthy();
    expect(within(dialog).getByText(ARGUMENTS)).toBeTruthy();
    expect(dialog.textContent).not.toContain(PAT);
    expect(document.body.textContent).not.toMatch(/will succeed/i);
    expect(api.mock.calls.some((call) => String(call[0]).includes("tools/call"))).toBe(false);

    fireEvent.click(within(dialog).getByRole("button", { name: "Confirm" }));
    expect(callPosts()).toHaveLength(1);
    const init = callPosts()[0][1] as RequestInit;
    expect(callPosts()[0][0]).toBe(`${ORIGIN}/mcp`);
    expect(init.method).toBe("POST");
    expect(init.credentials).toBe("omit");
    const headers = new Headers(init.headers);
    expect(headers.get("Authorization")).toBe(`Bearer ${PAT}`);
    expect(headers.get("mcp-method")).toBe("tools/call");
    expect(headers.get("mcp-name")).toBe("set_object_semantics");
    const payload = JSON.parse(String(init.body)) as {
      method: string;
      params: { name: string; arguments: unknown };
    };
    expect(payload.method).toBe("tools/call");
    expect(payload.params.name).toBe("set_object_semantics");
    expect(payload.params.arguments).toEqual({ object_id: "obj-7" });

    expect(await screen.findByRole("region", { name: "Tool result" })).toBeTruthy();
    expect(document.body.textContent).toContain("write-result");
    expect(callPosts()).toHaveLength(1);
  });

  it("blocks empty text, invalid JSON, and schema violations before confirmation", async () => {
    await readyWrite();
    typeArguments("");
    run("/mcp set_object_semantics");
    expect(screen.getByText("Arguments are empty.")).toBeTruthy();
    expect(screen.queryByRole("dialog")).toBeNull();
    expect(callPosts()).toHaveLength(0);

    typeArguments("   ");
    run("/mcp set_object_semantics");
    expect(screen.getByText("Arguments are empty.")).toBeTruthy();
    expect(editor().value).toBe("   ");
    expect(screen.queryByRole("dialog")).toBeNull();
    expect(callPosts()).toHaveLength(0);

    typeArguments("{");
    run("/mcp set_object_semantics");
    expect(screen.getByText(/Arguments are not valid JSON\./)).toBeTruthy();
    expect(screen.queryByRole("dialog")).toBeNull();
    expect(callPosts()).toHaveLength(0);

    typeArguments("{}");
    run("/mcp set_object_semantics");
    expect(screen.getByText(/arguments\.object_id is required/)).toBeTruthy();
    expect(screen.queryByRole("dialog")).toBeNull();
    expect(callPosts()).toHaveLength(0);

    typeArguments('{"object_id":1}');
    run("/mcp set_object_semantics");
    expect(screen.getByText(/arguments\.object_id must be string/)).toBeTruthy();
    expect(screen.queryByRole("dialog")).toBeNull();
    expect(callPosts()).toHaveLength(0);

    typeArguments('{"object_id":"obj-7","extra":true}');
    run("/mcp set_object_semantics");
    expect(screen.getByText(/arguments\.extra is not allowed/)).toBeTruthy();
    expect(screen.queryByRole("dialog")).toBeNull();
    expect(callPosts()).toHaveLength(0);
    expect(document.body.textContent).not.toMatch(/will succeed/i);
  });

  it("sends one tools/call for a snapshot and ignores another confirm", async () => {
    let release: (response: Response) => void = () => {};
    let capturedId: unknown;
    callResponder = (_url, body) => {
      capturedId = body.id;
      return new Promise<Response>((resolve) => {
        release = resolve;
      });
    };
    await readyWrite();
    run("/mcp set_object_semantics");
    confirmWrite();
    expect(callPosts()).toHaveLength(1);
    confirmWrite();
    expect(callPosts()).toHaveLength(1);
    expect(postedArguments()).toEqual({ object_id: "obj-7" });

    await act(async () => {
      release(jsonResponse(200, callEnvelope(capturedId, JSON.stringify({ rows: ["once-marker"] }))));
    });
    expect(await screen.findByRole("region", { name: "Tool result" })).toBeTruthy();
    expect(document.body.textContent).toContain("once-marker");
    confirmWrite();
    expect(callPosts()).toHaveLength(1);

    await act(async () => {
      await new Promise((resolve) => setTimeout(resolve, 0));
    });
    expect(callPosts()).toHaveLength(1);
  });

  it("does not send when confirmation is cancelled, and a later snapshot can send", async () => {
    await readyWrite();
    run("/mcp set_object_semantics");
    expect(screen.getByRole("dialog", { name: "Confirm this write" })).toBeTruthy();
    cancelWrite();
    expect(screen.queryByRole("dialog")).toBeNull();
    expect(callPosts()).toHaveLength(0);

    run("/mcp set_object_semantics");
    expect(within(screen.getByRole("dialog")).getByText(ARGUMENTS)).toBeTruthy();
    confirmWrite();
    expect(callPosts()).toHaveLength(1);
    expect(postedArguments()).toEqual({ object_id: "obj-7" });
  });

  it("keeps the dispatched snapshot when the editor changes and does not call the write cancelled", async () => {
    let release: (response: Response) => void = () => {};
    let capturedId: unknown;
    callResponder = (_url, body) => {
      capturedId = body.id;
      return new Promise<Response>((resolve) => {
        release = resolve;
      });
    };
    await readyWrite();
    typeArguments('{ "object_id" : "obj-7" }');
    run("/mcp set_object_semantics");
    const dialog = screen.getByRole("dialog", { name: "Confirm this write" });
    expect(within(dialog).getByText('{"object_id":"obj-7"}')).toBeTruthy();
    expect(dialog.textContent).not.toContain('{ "object_id" : "obj-7" }');
    confirmWrite();
    expect(callPosts()).toHaveLength(1);
    expect(postedArguments()).toEqual({ object_id: "obj-7" });

    typeArguments('{"object_id":"obj-8"}');
    expect(callPosts()).toHaveLength(1);
    expect(postedArguments()).toEqual({ object_id: "obj-7" });
    expect(editor().value).toBe('{"object_id":"obj-8"}');

    cancelWrite();
    expect(screen.queryByRole("dialog")).toBeNull();
    expect(callPosts()).toHaveLength(1);
    expect(document.body.textContent).not.toMatch(/unknown outcome|rolled back|write was cancelled|write was canceled/i);

    await act(async () => {
      release(jsonResponse(200, callEnvelope(capturedId, JSON.stringify({ rows: ["kept-snapshot-marker"] }))));
    });
    expect(document.body.textContent).toContain("kept-snapshot-marker");
    expect(callPosts()).toHaveLength(1);
    expect(document.body.textContent).not.toMatch(/unknown outcome|rolled back|write was cancelled|write was canceled/i);
  });

  it("drops an unsent snapshot when the arguments, tool, endpoint, or User PAT changes", async () => {
    const view = await readyWrite();
    run("/mcp set_object_semantics");
    expect(screen.getByRole("dialog")).toBeTruthy();

    typeArguments('{ "object_id": "obj-7" }');
    expect(screen.queryByRole("dialog")).toBeNull();
    expect(callPosts()).toHaveLength(0);
    run("/mcp set_object_semantics");
    expect(within(screen.getByRole("dialog")).getByText('{"object_id":"obj-7"}')).toBeTruthy();
    expect(callPosts()).toHaveLength(0);

    await selectTool("/mcp run_sql");
    expect(screen.queryByRole("dialog")).toBeNull();
    expect(editor().value).toBe("");
    expect(callPosts()).toHaveLength(0);

    await selectTool("/mcp set_object_semantics");
    typeArguments(ARGUMENTS);
    run("/mcp set_object_semantics");
    expect(screen.getByRole("dialog")).toBeTruthy();

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
    expect(screen.queryByRole("dialog")).toBeNull();
    expect(screen.queryByRole("textbox", { name: "Arguments" })).toBeNull();
    expect(callPosts()).toHaveLength(0);
    expect((screen.getByLabelText("User PAT") as HTMLInputElement).value).toBe(PAT);

    pathname.current = "/console/mcp/metadata";
    view.rerender(
      shell(
        createElement(
          (await import("@/app/console/mcp/layout")).default,
          null,
          createElement((await import("@/features/mcp/McpMetadataDetail")).McpMetadataDetail),
        ),
      ),
    );
    verifyPat();
    await screen.findByRole("button", { name: "Discover tools" });
    await discover();
    await selectTool("/mcp set_object_semantics");
    typeArguments(ARGUMENTS);
    run("/mcp set_object_semantics");
    expect(screen.getByRole("dialog")).toBeTruthy();
    expect(callPosts()).toHaveLength(0);

    fireEvent.change(screen.getByLabelText("User PAT"), { target: { value: `${PAT}-edited` } });
    expect(screen.queryByRole("dialog")).toBeNull();
    expect(screen.queryByRole("textbox", { name: "Arguments" })).toBeNull();
    expect(callPosts()).toHaveLength(0);
    expect((screen.getByLabelText("User PAT") as HTMLInputElement).value).toBe(`${PAT}-edited`);
  });

  it("does not apply a late write after the endpoint or User PAT changes", async () => {
    let release: (response: Response) => void = () => {};
    let capturedId: unknown;
    callResponder = (_url, body) => {
      capturedId = body.id;
      return new Promise<Response>((resolve) => {
        release = resolve;
      });
    };
    const view = await readyWrite();
    run("/mcp set_object_semantics");
    confirmWrite();
    expect(callPosts()).toHaveLength(1);

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
    expect(screen.queryByRole("dialog")).toBeNull();
    await act(async () => {
      release(jsonResponse(200, callEnvelope(capturedId, JSON.stringify({ rows: ["late-endpoint-marker"] }))));
    });
    expect(document.body.textContent).not.toContain("late-endpoint-marker");
    expect(callPosts()).toHaveLength(1);
    expect(document.body.textContent).not.toMatch(/unknown outcome|rolled back|write was cancelled|write was canceled/i);

    pathname.current = "/console/mcp/metadata";
    view.rerender(
      shell(
        createElement(
          (await import("@/app/console/mcp/layout")).default,
          null,
          createElement((await import("@/features/mcp/McpMetadataDetail")).McpMetadataDetail),
        ),
      ),
    );
    verifyPat();
    await screen.findByRole("button", { name: "Discover tools" });
    await discover();
    await selectTool("/mcp set_object_semantics");
    typeArguments(ARGUMENTS);
    run("/mcp set_object_semantics");
    confirmWrite();
    expect(callPosts()).toHaveLength(2);

    fireEvent.change(screen.getByLabelText("User PAT"), { target: { value: `${PAT}-next` } });
    await act(async () => {
      release(jsonResponse(200, callEnvelope(capturedId, JSON.stringify({ rows: ["late-pat-marker"] }))));
    });
    expect(document.body.textContent).not.toContain("late-pat-marker");
    expect(document.body.textContent).not.toContain("late-endpoint-marker");
    expect(callPosts()).toHaveLength(2);
    expect(screen.queryByRole("dialog")).toBeNull();
  });

  it("asks again for the next write and does not confirm a read", async () => {
    await readyWrite();
    run("/mcp set_object_semantics");
    confirmWrite();
    expect(await screen.findByRole("region", { name: "Tool result" })).toBeTruthy();
    expect(callPosts()).toHaveLength(1);

    run("/mcp set_object_semantics");
    expect(callPosts()).toHaveLength(1);
    expect(within(screen.getByRole("dialog")).getByText(NOTICE)).toBeTruthy();
    confirmWrite();
    expect(callPosts()).toHaveLength(2);
    expect(postedArguments(1)).toEqual({ object_id: "obj-7" });

    await selectTool("/mcp run_sql");
    expect(screen.queryByRole("dialog")).toBeNull();
    typeArguments('{"statement":"select 1"}');
    expect(callPosts()).toHaveLength(2);
    run("/mcp run_sql");
    expect(callPosts()).toHaveLength(3);
    expect(screen.queryByRole("dialog")).toBeNull();
    expect(postedArguments(2)).toEqual({ statement: "select 1" });

    await selectTool("/mcp set_column_semantics");
    expect(screen.queryByRole("dialog")).toBeNull();
    typeArguments('{"object_id":"col-1"}');
    run("/mcp set_column_semantics");
    expect(callPosts()).toHaveLength(4);
    expect(screen.queryByRole("dialog")).toBeNull();
    expect(postedArguments(3)).toEqual({ object_id: "col-1" });

    await selectTool("/mcp upsert_join");
    typeArguments('{"left_id":"left-1"}');
    run("/mcp upsert_join");
    expect(callPosts()).toHaveLength(4);
    expect(within(screen.getByRole("dialog")).getByText("Tool upsert_join")).toBeTruthy();
    expect(within(screen.getByRole("dialog")).getByText('{"left_id":"left-1"}')).toBeTruthy();
    expect(screen.getByRole("dialog").textContent).not.toContain(PAT);
  });

  it("runs an Entity read directly and does not keep a Metadata write confirmation", async () => {
    const view = await readyWrite();
    run("/mcp set_object_semantics");
    expect(screen.getByRole("dialog")).toBeTruthy();

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
    expect(screen.queryByRole("dialog")).toBeNull();
    expect(callPosts()).toHaveLength(0);
    fireEvent.click(screen.getByRole("button", { name: "Discover tools" }));
    expect(await screen.findByRole("listitem", { name: "/mcp/entity validate_sql" })).toBeTruthy();
    expect(screen.getByRole("listitem", { name: "/mcp/entity run_sql" })).toBeTruthy();

    await selectTool("/mcp/entity validate_sql");
    typeArguments('{"query":"select 1"}');
    run("/mcp/entity validate_sql");
    expect(callPosts()).toHaveLength(1);
    expect(screen.queryByRole("dialog")).toBeNull();
    expect(callPosts()[0][0]).toBe(`${ORIGIN}/mcp/entity`);
    expect(postedArguments()).toEqual({ query: "select 1" });

    await selectTool("/mcp/entity run_sql");
    expect(screen.queryByRole("dialog")).toBeNull();
    typeArguments('{"query":"select 2"}');
    run("/mcp/entity run_sql");
    expect(callPosts()).toHaveLength(2);
    expect(screen.queryByRole("dialog")).toBeNull();
    expect(postedArguments(1)).toEqual({ query: "select 2" });
    expect(screen.getByRole("button", { name: "Run /mcp/entity run_sql" })).toBeTruthy();
  });

  it("gives a missing execution class no run and no confirm", async () => {
    await renderMetadata();
    verifyPat();
    await screen.findByRole("button", { name: "Discover tools" });
    await discover();
    for (const name of [
      "/mcp search_sources",
      "/mcp hint_only",
      "/mcp blank_class",
      "/mcp rename_object",
      "/mcp get_object",
    ]) {
      await selectTool(name);
      expect(screen.queryByRole("button", { name: /^Run / })).toBeNull();
      expect(screen.queryByRole("button", { name: "Confirm" })).toBeNull();
      expect(screen.queryByRole("dialog")).toBeNull();
    }
    expect(callPosts()).toHaveLength(0);
  });

  it("forgets a write confirmation when the workspace unmounts and does not store it", async () => {
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
    let release: (response: Response) => void = () => {};
    let capturedId: unknown;
    callResponder = (_url, body) => {
      capturedId = body.id;
      return new Promise<Response>((resolve) => {
        release = resolve;
      });
    };

    const view = await readyWrite();
    run("/mcp set_object_semantics");
    expect(screen.getByRole("dialog")).toBeTruthy();
    confirmWrite();
    expect(callPosts()).toHaveLength(1);
    const stored = writes.join("\n");
    expect(stored).not.toContain("obj-7");
    expect(stored).not.toContain(PAT);
    expect(stored).not.toContain("writeConfirm");
    expect(window.location.href).toBe("https://console.example.com/console/mcp/metadata");
    expect(window.location.search).toBe("");
    expect(opens).not.toHaveBeenCalled();

    view.unmount();
    await renderMetadata();
    expect(callPosts()).toHaveLength(1);
    expect(screen.queryByRole("dialog")).toBeNull();
    expect((screen.getByLabelText("User PAT") as HTMLInputElement).value).toBe("");
    expect(document.body.textContent).not.toContain("obj-7");
    expect(screen.queryByRole("button", { name: "Discover tools" })).toBeNull();

    await act(async () => {
      release(jsonResponse(200, callEnvelope(capturedId, JSON.stringify({ rows: ["revived-marker"] }))));
      await new Promise((resolve) => setTimeout(resolve, 0));
    });
    expect(document.body.textContent).not.toContain("revived-marker");
    expect(callPosts()).toHaveLength(1);
    expect(screen.queryByRole("dialog")).toBeNull();
  });

  it("keeps a Console session signed in when a confirmed write returns 401", async () => {
    callResponder = () =>
      jsonResponse(
        401,
        {
          type: "urn:refraq:problem:AUTH_UNAUTHENTICATED",
          status: 401,
          detail: "Not signed in or session expired",
          code: "AUTH_UNAUTHENTICATED",
        },
        "application/problem+json",
      );
    await readyWrite();
    run("/mcp set_object_semantics");
    confirmWrite();
    expect(
      await screen.findByRole("region", {
        name: "The call failed in HTTP or the proxy, before a tool result.",
      }),
    ).toBeTruthy();
    expect(document.body.textContent).not.toContain("Not signed in or session expired");
    expect(useSessionStore.getState().user?.id).toBe("user-a");
    expect(useSessionStore.getState().signedOutLocally).toBe(false);
    expect(window.location.pathname).toBe("/console/mcp/metadata");
    expect(callPosts()).toHaveLength(1);
    expect(api.mock.calls.some((call) => String(call[0]).includes("tools/call"))).toBe(false);
  });

  it("keeps an unsent confirmation when a refresh still classifies the tool as write", async () => {
    await readyWrite();
    run("/mcp set_object_semantics");
    expect(screen.getByRole("dialog", { name: "Confirm this write" })).toBeTruthy();
    metadataOverride = semanticsCatalog("write", "Write object semantics refreshed.");
    fireEvent.click(screen.getByRole("button", { name: "Discover tools" }));
    expect(await screen.findByText("Write object semantics refreshed.")).toBeTruthy();
    expect(screen.getByRole("dialog", { name: "Confirm this write" })).toBeTruthy();
    expect(within(screen.getByRole("dialog")).getByText(ARGUMENTS)).toBeTruthy();
    expect(callPosts()).toHaveLength(0);
  });

  it("drops an unsent confirmation when a refresh no longer classifies the tool as write", async () => {
    await readyWrite();
    run("/mcp set_object_semantics");
    expect(screen.getByRole("dialog", { name: "Confirm this write" })).toBeTruthy();
    metadataOverride = semanticsCatalog("read", "Semantics published as a read.");
    fireEvent.click(screen.getByRole("button", { name: "Discover tools" }));
    expect(await screen.findByText("Semantics published as a read.")).toBeTruthy();
    expect(screen.queryByRole("dialog")).toBeNull();
    expect(callPosts()).toHaveLength(0);

    run("/mcp set_object_semantics");
    expect(screen.queryByRole("dialog")).toBeNull();
    expect(callPosts()).toHaveLength(1);
    expect(postedArguments()).toEqual({ object_id: "obj-7" });
  });

  it("keeps an in-flight write when a refresh reclassifies the tool", async () => {
    let release: (response: Response) => void = () => {};
    let capturedId: unknown;
    callResponder = (_url, body) => {
      capturedId = body.id;
      return new Promise<Response>((resolve) => {
        release = resolve;
      });
    };
    await readyWrite();
    run("/mcp set_object_semantics");
    confirmWrite();
    expect(callPosts()).toHaveLength(1);
    metadataOverride = semanticsCatalog("read", "Semantics published as a read.");
    fireEvent.click(screen.getByRole("button", { name: "Discover tools" }));
    expect(await screen.findByText("Semantics published as a read.")).toBeTruthy();
    expect(screen.getByRole("dialog", { name: "Confirm this write" })).toBeTruthy();
    expect(callPosts()).toHaveLength(1);

    await act(async () => {
      release(jsonResponse(200, callEnvelope(capturedId, JSON.stringify({ rows: ["kept-inflight-marker"] }))));
    });
    expect(document.body.textContent).toContain("kept-inflight-marker");
    expect(callPosts()).toHaveLength(1);
    expect(document.body.textContent).not.toMatch(/unknown outcome|rolled back|write was cancelled|write was canceled/i);
  });

  it("restores an unsent confirmation after an unreadable refresh when the tool is write again", async () => {
    await readyWrite();
    run("/mcp set_object_semantics");
    expect(screen.getByRole("dialog", { name: "Confirm this write" })).toBeTruthy();
    metadataUnreadable = true;
    fireEvent.click(screen.getByRole("button", { name: "Discover tools" }));
    expect(
      await screen.findByText("The tool list response could not be read. That is not an empty catalog."),
    ).toBeTruthy();
    expect(screen.queryByRole("dialog")).toBeNull();
    expect(callPosts()).toHaveLength(0);

    metadataUnreadable = false;
    fireEvent.click(screen.getByRole("button", { name: "Discover tools" }));
    expect(await screen.findByRole("listitem", { name: "/mcp set_object_semantics" })).toBeTruthy();
    expect(screen.getByRole("dialog", { name: "Confirm this write" })).toBeTruthy();
    expect(within(screen.getByRole("dialog")).getByText(ARGUMENTS)).toBeTruthy();
    expect(callPosts()).toHaveLength(0);
  });
});
