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

const PAT = "rfqpat-distinct-secret-08";
const ORIGIN = "https://console.example.com";
const ARGUMENTS = '{"object_id":"obj-7"}';
const STOP = "Stop waiting";
const STOPPED = "Waiting stopped.";
const CANCELLATION = "Cancellation was requested.";
const UNKNOWN = "The outcome is unknown. The change may have committed. Inspect the business state.";
const HTTP_FAILURE = "The call failed in HTTP or the proxy, before a tool result.";
const TRANSPORT_FAILURE = "The call response could not be read.";
const PROTOCOL_ERROR = "The call returned a protocol error.";
const SDK_ERROR = "The tool returned an error.";
const DOMAIN_ERROR = "The tool returned a domain error.";
const EMPTY_CATALOG = "This endpoint returned no tools. That is an empty catalog.";
const UNAVAILABLE = "This endpoint is unavailable.";
const FALSE_PROMISE = /rolled back|rollback|tool failed/i;

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
      _meta: { "io.refraq/execution": "write" },
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
      _meta: { "io.refraq/execution": "read" },
    },
    {
      name: "hint_only",
      description: "Hint without a class.",
      inputSchema: { type: "object" },
      annotations: { readOnlyHint: true },
    },
  ];
}

function entityTools() {
  return [
    {
      name: "run_sql",
      description: "Run entity SQL.",
      inputSchema: {
        type: "object",
        additionalProperties: false,
        required: ["query"],
        properties: { query: { type: "string", minLength: 1 } },
      },
      _meta: { "io.refraq/execution": "read" },
    },
  ];
}

function toolMessage(id: unknown, tools: unknown[]) {
  return { jsonrpc: "2.0", id, result: { tools } };
}

function callEnvelope(id: unknown, text: string, isError = false) {
  return {
    jsonrpc: "2.0",
    id,
    result: {
      content: [{ type: "text", text }],
      isError,
      structuredContent: { result: text },
    },
  };
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
  jsonResponse(200, callEnvelope(body.id, JSON.stringify({ rows: ["write-result"] })));
let listMode: "ok" | "hold" | "bad-gateway" = "ok";
let releaseList: (response: Response) => void = () => {};

function installFetch() {
  vi.stubGlobal(
    "fetch",
    vi.fn(async (url: string, init?: RequestInit) => {
      if (String(url).endsWith("/auth/me")) return jsonResponse(200, meBody("user-a"));
      const body = typeof init?.body === "string" ? JSON.parse(init.body) : {};
      if (body.method === "tools/call") return callResponder(String(url), body, init);
      if (body.method === "tools/list" && String(url) === `${ORIGIN}/mcp`) {
        if (listMode === "hold") {
          return new Promise<Response>((resolve) => {
            releaseList = resolve;
          });
        }
        if (listMode === "bad-gateway") return jsonResponse(502, { error: "list-down" });
      }
      if (String(url) === `${ORIGIN}/mcp/entity`) return jsonResponse(200, toolMessage(body.id, entityTools()));
      return jsonResponse(200, toolMessage(body.id, metadataTools()));
    }),
  );
}

function methodPosts(method: string) {
  return vi.mocked(fetch).mock.calls.filter((call) => {
    const init = call[1] as RequestInit | undefined;
    return new Headers(init?.headers).get("mcp-method") === method;
  });
}

function callPosts() {
  return methodPosts("tools/call");
}

function listPosts() {
  return methodPosts("tools/list");
}

function callSignal(index = 0): AbortSignal {
  const init = callPosts()[index][1] as RequestInit;
  if (!(init.signal instanceof AbortSignal)) {
    throw new Error("tools/call was sent without an AbortSignal");
  }
  return init.signal;
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

async function showMetadata(view: { rerender: (node: ReactNode) => void }) {
  const { default: Layout } = await import("@/app/console/mcp/layout");
  const { McpMetadataDetail } = await import("@/features/mcp/McpMetadataDetail");
  view.rerender(shell(createElement(Layout, null, createElement(McpMetadataDetail))));
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

function storageDump(storage: Storage) {
  const values: string[] = [];
  for (let index = 0; index < storage.length; index += 1) {
    const key = storage.key(index);
    if (!key) continue;
    values.push(key, storage.getItem(key) ?? "");
  }
  return values.join("\n");
}

describe("MCP interruption and unknown write outcome", () => {
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
    listMode = "ok";
    releaseList = () => {};
    installFetch();
  });

  afterEach(() => {
    cleanup();
    resetSessionStoreForTests();
    vi.unstubAllGlobals();
    vi.restoreAllMocks();
  });

  it("stops waiting on a dispatched write without promising rollback or tool failure", async () => {
    let release: (response: Response) => void = () => {};
    callResponder = () =>
      new Promise<Response>((resolve) => {
        release = resolve;
      });
    await readyWrite();
    run("/mcp set_object_semantics");
    expect(screen.queryByRole("button", { name: STOP })).toBeNull();
    confirmWrite();
    const stop = await screen.findByRole("button", { name: STOP });
    expect(callPosts()).toHaveLength(1);
    expect(callSignal().aborted).toBe(false);

    fireEvent.click(stop);
    expect(screen.queryByRole("button", { name: STOP })).toBeNull();
    expect(screen.getByText(CANCELLATION)).toBeTruthy();
    expect(screen.getByRole("region", { name: UNKNOWN })).toBeTruthy();
    expect(document.body.textContent).not.toMatch(FALSE_PROMISE);
    expect(screen.queryByRole("region", { name: SDK_ERROR })).toBeNull();
    expect(callSignal().aborted).toBe(true);
    expect(callPosts()).toHaveLength(1);

    await act(async () => {
      release(jsonResponse(200, callEnvelope(1, JSON.stringify({ rows: ["late-stop-marker"] }))));
    });
    expect(document.body.textContent).not.toContain("late-stop-marker");
    expect(document.body.textContent).not.toMatch(FALSE_PROMISE);
    expect(callPosts()).toHaveLength(1);
  });

  it("keeps an unknown write unknown, does not retry it, and requires a new confirmation", async () => {
    let release: (response: Response) => void = () => {};
    let mode: "hold" | "ok" = "hold";
    callResponder = (_url, body) => {
      if (mode === "hold") {
        return new Promise<Response>((resolve) => {
          release = resolve;
        });
      }
      return jsonResponse(200, callEnvelope(body.id, JSON.stringify({ rows: ["second-snapshot-marker"] })));
    };
    await readyWrite();
    run("/mcp set_object_semantics");
    confirmWrite();
    fireEvent.click(await screen.findByRole("button", { name: STOP }));
    expect(screen.getByRole("region", { name: UNKNOWN })).toBeTruthy();
    expect(screen.getByText(CANCELLATION)).toBeTruthy();
    expect(screen.queryByRole("button", { name: /retry/i })).toBeNull();
    expect(callPosts()).toHaveLength(1);
    expect(postedArguments()).toEqual({ object_id: "obj-7" });

    await act(async () => {
      await new Promise((resolve) => setTimeout(resolve, 0));
      release(jsonResponse(200, callEnvelope(1, JSON.stringify({ rows: ["retry-marker"] }))));
    });
    expect(callPosts()).toHaveLength(1);
    expect(document.body.textContent).not.toContain("retry-marker");
    expect(screen.queryByRole("button", { name: /retry/i })).toBeNull();

    mode = "ok";
    typeArguments('{"object_id":"obj-8"}');
    run("/mcp set_object_semantics");
    expect(callPosts()).toHaveLength(1);
    const dialog = screen.getByRole("dialog", { name: "Confirm this write" });
    expect(within(dialog).getByText('{"object_id":"obj-8"}')).toBeTruthy();
    confirmWrite();
    expect(callPosts()).toHaveLength(2);
    expect(postedArguments(0)).toEqual({ object_id: "obj-7" });
    expect(postedArguments(1)).toEqual({ object_id: "obj-8" });
    expect((await screen.findByRole("region", { name: "Tool result" })).textContent).toContain(
      "second-snapshot-marker",
    );
    expect(screen.queryByRole("region", { name: UNKNOWN })).toBeNull();
  });

  it("treats a lost write response as unknown and keeps a conclusive response classified", async () => {
    await readyWrite();

    callResponder = () => jsonResponse(502, { error: "upstream-marker" });
    run("/mcp set_object_semantics");
    confirmWrite();
    expect(await screen.findByRole("region", { name: UNKNOWN })).toBeTruthy();
    expect(screen.queryByText(CANCELLATION)).toBeNull();
    expect(screen.queryByRole("region", { name: HTTP_FAILURE })).toBeNull();
    expect(document.body.textContent).not.toContain("upstream-marker");
    expect(screen.queryByRole("button", { name: /retry/i })).toBeNull();
    await act(async () => {
      await new Promise((resolve) => setTimeout(resolve, 0));
    });
    expect(callPosts()).toHaveLength(1);
    run("/mcp set_object_semantics");
    expect(callPosts()).toHaveLength(1);
    expect(screen.getByRole("dialog", { name: "Confirm this write" })).toBeTruthy();
    cancelWrite();
    expect(callPosts()).toHaveLength(1);

    callResponder = () => {
      throw new Error("network-marker");
    };
    run("/mcp set_object_semantics");
    confirmWrite();
    expect(await screen.findByRole("region", { name: UNKNOWN })).toBeTruthy();
    expect(screen.queryByRole("region", { name: HTTP_FAILURE })).toBeNull();
    expect(screen.queryByText(CANCELLATION)).toBeNull();
    expect(document.body.textContent).not.toContain("network-marker");
    expect(callPosts()).toHaveLength(2);

    callResponder = () => {
      const stream = new ReadableStream({
        start(controller) {
          controller.error(new Error("body-marker"));
        },
      });
      return new Response(stream, { status: 200, headers: { "Content-Type": "application/json" } });
    };
    run("/mcp set_object_semantics");
    confirmWrite();
    expect(await screen.findByRole("region", { name: UNKNOWN })).toBeTruthy();
    expect(screen.queryByRole("region", { name: TRANSPORT_FAILURE })).toBeNull();
    expect(document.body.textContent).not.toContain("body-marker");
    expect(callPosts()).toHaveLength(3);

    const conclusive: Array<{
      respond: CallResponder;
      region: string;
      present: string[];
      absent: string[];
    }> = [
      {
        respond: (_url, body) =>
          jsonResponse(200, callEnvelope(body.id, JSON.stringify({ rows: ["ok-marker"] }))),
        region: "Tool result",
        present: ["ok-marker"],
        absent: [UNKNOWN, HTTP_FAILURE],
      },
      {
        respond: (_url, body) =>
          jsonResponse(200, { jsonrpc: "2.0", id: body.id, error: { code: -32000, message: "protocol-marker" } }),
        region: PROTOCOL_ERROR,
        present: ["protocol-marker"],
        absent: [UNKNOWN, "Tool result"],
      },
      {
        respond: (_url, body) => jsonResponse(200, callEnvelope(body.id, "sdk-marker", true)),
        region: SDK_ERROR,
        present: ["sdk-marker"],
        absent: [UNKNOWN, DOMAIN_ERROR],
      },
      {
        respond: (_url, body) =>
          jsonResponse(200, callEnvelope(body.id, domainText("SOURCE_NOT_FOUND", "domain-marker"))),
        region: DOMAIN_ERROR,
        present: ["SOURCE_NOT_FOUND", "domain-marker"],
        absent: [UNKNOWN, SDK_ERROR],
      },
      {
        respond: () =>
          jsonResponse(
            403,
            {
              type: "urn:refraq:problem:FORBIDDEN",
              title: "Forbidden",
              status: 403,
              detail: "problem-marker",
            },
            "application/problem+json",
          ),
        region: HTTP_FAILURE,
        present: [],
        absent: [UNKNOWN, PROTOCOL_ERROR],
      },
    ];

    for (const item of conclusive) {
      callResponder = item.respond;
      const before = callPosts().length;
      run("/mcp set_object_semantics");
      confirmWrite();
      expect(await screen.findByRole("region", { name: item.region })).toBeTruthy();
      expect(callPosts()).toHaveLength(before + 1);
      for (const text of item.present) expect(document.body.textContent).toContain(text);
      for (const text of item.absent) {
        expect(screen.queryByRole("region", { name: text })).toBeNull();
      }
    }
    expect(document.body.textContent).not.toContain("problem-marker");
    expect(callPosts()).toHaveLength(8);
  });

  it("calls a stopped read or tool list an interrupted wait, not an unknown write", async () => {
    let releaseRead: (response: Response) => void = () => {};
    callResponder = () =>
      new Promise<Response>((resolve) => {
        releaseRead = resolve;
      });
    await readyWrite();
    await selectTool("/mcp run_sql");
    typeArguments('{"statement":"select 1"}');
    expect(screen.queryByRole("button", { name: STOP })).toBeNull();
    run("/mcp run_sql");
    fireEvent.click(await screen.findByRole("button", { name: STOP }));
    expect(screen.getByRole("region", { name: STOPPED })).toBeTruthy();
    expect(screen.queryByRole("button", { name: STOP })).toBeNull();
    expect(screen.queryByRole("region", { name: UNKNOWN })).toBeNull();
    expect(screen.queryByText(CANCELLATION)).toBeNull();
    expect(screen.queryByRole("region", { name: HTTP_FAILURE })).toBeNull();
    expect(screen.queryByRole("region", { name: TRANSPORT_FAILURE })).toBeNull();
    expect(screen.queryByText(EMPTY_CATALOG)).toBeNull();
    expect(screen.queryByText(UNAVAILABLE)).toBeNull();
    expect(document.body.textContent).not.toMatch(FALSE_PROMISE);
    expect(callPosts()).toHaveLength(1);
    expect(callSignal().aborted).toBe(true);

    await act(async () => {
      releaseRead(jsonResponse(200, callEnvelope(1, JSON.stringify({ rows: ["late-read-marker"] }))));
    });
    expect(document.body.textContent).not.toContain("late-read-marker");
    expect(callPosts()).toHaveLength(1);
    expect(screen.getByRole("region", { name: STOPPED })).toBeTruthy();

    callResponder = () => jsonResponse(502, { error: "read-upstream-marker" });
    run("/mcp run_sql");
    expect(await screen.findByRole("region", { name: HTTP_FAILURE })).toBeTruthy();
    expect(screen.queryByRole("region", { name: STOPPED })).toBeNull();
    expect(screen.queryByRole("region", { name: UNKNOWN })).toBeNull();
    expect(document.body.textContent).not.toContain("read-upstream-marker");

    callResponder = () => {
      const stream = new ReadableStream({
        start(controller) {
          controller.error(new Error("read-body-marker"));
        },
      });
      return new Response(stream, { status: 200, headers: { "Content-Type": "application/json" } });
    };
    run("/mcp run_sql");
    expect(await screen.findByRole("region", { name: TRANSPORT_FAILURE })).toBeTruthy();
    expect(screen.queryByRole("region", { name: UNKNOWN })).toBeNull();
    expect(screen.queryByRole("region", { name: STOPPED })).toBeNull();
    expect(document.body.textContent).not.toContain("read-body-marker");
    expect(callPosts()).toHaveLength(3);

    cleanup();
    listMode = "hold";
    installFetch();
    await renderMetadata();
    verifyPat();
    await screen.findByRole("button", { name: "Discover tools" });
    fireEvent.click(screen.getByRole("button", { name: "Discover tools" }));
    fireEvent.click(await screen.findByRole("button", { name: STOP }));
    expect(screen.getByText(STOPPED)).toBeTruthy();
    expect(screen.queryByText(EMPTY_CATALOG)).toBeNull();
    expect(screen.queryByText(UNAVAILABLE)).toBeNull();
    expect(screen.queryByText(UNKNOWN)).toBeNull();
    expect(screen.queryByRole("button", { name: STOP })).toBeNull();
    expect(listPosts()).toHaveLength(1);
    expect(callPosts()).toHaveLength(0);
    const listSignal = (listPosts()[0][1] as RequestInit).signal as AbortSignal;
    expect(listSignal.aborted).toBe(true);

    await act(async () => {
      releaseList(jsonResponse(200, toolMessage(1, metadataTools())));
    });
    expect(screen.queryByRole("listitem", { name: "/mcp set_object_semantics" })).toBeNull();
    expect(screen.getByText(STOPPED)).toBeTruthy();
    expect(listPosts()).toHaveLength(1);

    listMode = "bad-gateway";
    fireEvent.click(screen.getByRole("button", { name: "Discover tools" }));
    expect(await screen.findByText(UNAVAILABLE)).toBeTruthy();
    expect(screen.queryByText(STOPPED)).toBeNull();
    expect(screen.queryByText(EMPTY_CATALOG)).toBeNull();
    expect(listPosts()).toHaveLength(2);
  });

  it("does not call a pre-dispatch rejection or a closed confirmation an unknown write", async () => {
    let release: (response: Response) => void = () => {};
    let capturedId: unknown;
    callResponder = (_url, body) => {
      capturedId = body.id;
      return new Promise<Response>((resolve) => {
        release = resolve;
      });
    };
    await readyWrite();

    typeArguments("{");
    run("/mcp set_object_semantics");
    expect(screen.getByText(/Arguments are not valid JSON\./)).toBeTruthy();
    expect(screen.queryByRole("dialog")).toBeNull();
    expect(screen.queryByRole("region", { name: UNKNOWN })).toBeNull();
    expect(screen.queryByRole("button", { name: STOP })).toBeNull();
    expect(callPosts()).toHaveLength(0);

    typeArguments("{}");
    run("/mcp set_object_semantics");
    expect(screen.getByText(/arguments\.object_id is required/)).toBeTruthy();
    expect(screen.queryByRole("dialog")).toBeNull();
    expect(screen.queryByRole("region", { name: UNKNOWN })).toBeNull();
    expect(callPosts()).toHaveLength(0);

    await selectTool("/mcp hint_only");
    expect(screen.queryByRole("button", { name: /Run / })).toBeNull();
    expect(screen.queryByRole("region", { name: UNKNOWN })).toBeNull();
    expect(callPosts()).toHaveLength(0);

    await selectTool("/mcp set_object_semantics");
    typeArguments(ARGUMENTS);
    run("/mcp set_object_semantics");
    expect(screen.getByRole("dialog", { name: "Confirm this write" })).toBeTruthy();
    cancelWrite();
    expect(screen.queryByRole("dialog")).toBeNull();
    expect(screen.queryByRole("region", { name: UNKNOWN })).toBeNull();
    expect(screen.queryByText(CANCELLATION)).toBeNull();
    expect(screen.queryByText(STOPPED)).toBeNull();
    expect(callPosts()).toHaveLength(0);

    run("/mcp set_object_semantics");
    confirmWrite();
    expect(callPosts()).toHaveLength(1);
    expect(callSignal().aborted).toBe(false);
    cancelWrite();
    expect(screen.queryByRole("dialog")).toBeNull();
    expect(screen.queryByRole("region", { name: UNKNOWN })).toBeNull();
    expect(screen.queryByText(CANCELLATION)).toBeNull();
    expect(screen.queryByText(STOPPED)).toBeNull();
    expect(callSignal().aborted).toBe(false);
    expect(screen.getByRole("button", { name: STOP })).toBeTruthy();

    await act(async () => {
      release(jsonResponse(200, callEnvelope(capturedId, JSON.stringify({ rows: ["kept-after-close-marker"] }))));
    });
    expect(document.body.textContent).toContain("kept-after-close-marker");
    expect(screen.queryByRole("region", { name: UNKNOWN })).toBeNull();
    expect(screen.queryByText(CANCELLATION)).toBeNull();
    expect(callPosts()).toHaveLength(1);
  });

  it("does not replay discovery, run, or confirmation on refresh, return, or reconnect", async () => {
    let release: (response: Response) => void = () => {};
    let capturedId: unknown;
    callResponder = (_url, body) => {
      capturedId = body.id;
      return new Promise<Response>((resolve) => {
        release = resolve;
      });
    };
    const view = await renderMetadata();
    verifyPat();
    await screen.findByRole("button", { name: "Discover tools" });
    expect(listPosts()).toHaveLength(0);
    expect(callPosts()).toHaveLength(0);

    await discover();
    expect(listPosts()).toHaveLength(1);
    await selectTool("/mcp set_object_semantics");
    typeArguments(ARGUMENTS);
    run("/mcp set_object_semantics");
    expect(screen.getByRole("dialog")).toBeTruthy();
    expect(callPosts()).toHaveLength(0);

    const catalogBefore = api.mock.calls.length;
    const { default: Layout } = await import("@/app/console/mcp/layout");
    view.rerender(shell(createElement(Layout, null, null)));
    await showMetadata(view);
    expect(await screen.findByRole("dialog", { name: "Confirm this write" })).toBeTruthy();
    expect(api.mock.calls.length).toBeGreaterThan(catalogBefore);
    expect(listPosts()).toHaveLength(1);
    expect(callPosts()).toHaveLength(0);

    confirmWrite();
    expect(callPosts()).toHaveLength(1);
    expect(callSignal().aborted).toBe(false);
    view.rerender(shell(createElement(Layout, null, null)));
    await showMetadata(view);
    expect(callPosts()).toHaveLength(1);
    expect(listPosts()).toHaveLength(1);
    expect(callSignal().aborted).toBe(false);

    await act(async () => {
      window.dispatchEvent(new Event("online"));
    });
    expect(callPosts()).toHaveLength(1);
    expect(listPosts()).toHaveLength(1);
    expect(callSignal().aborted).toBe(false);

    const { McpOverview } = await import("@/features/mcp/McpOverview");
    view.rerender(shell(createElement(Layout, null, createElement(McpOverview))));
    await showMetadata(view);
    expect(await screen.findByRole("button", { name: STOP })).toBeTruthy();
    expect(callPosts()).toHaveLength(1);
    expect(listPosts()).toHaveLength(1);
    expect(callSignal().aborted).toBe(false);

    await act(async () => {
      release(jsonResponse(200, callEnvelope(capturedId, JSON.stringify({ rows: ["same-endpoint-marker"] }))));
    });
    expect(document.body.textContent).toContain("same-endpoint-marker");
    expect(screen.queryByRole("region", { name: UNKNOWN })).toBeNull();
    expect(callPosts()).toHaveLength(1);
    expect(listPosts()).toHaveLength(1);
  });

  it("drops a late response when the User PAT is replaced", async () => {
    let release: (response: Response) => void = () => {};
    callResponder = () =>
      new Promise<Response>((resolve) => {
        release = resolve;
      });
    await readyWrite();
    run("/mcp set_object_semantics");
    expect(screen.getByRole("dialog")).toBeTruthy();
    fireEvent.change(screen.getByLabelText("Personal access token"), { target: { value: `${PAT}-next` } });
    expect(screen.queryByRole("dialog")).toBeNull();
    expect(screen.queryByRole("region", { name: UNKNOWN })).toBeNull();
    expect(callPosts()).toHaveLength(0);

    verifyPat();
    await screen.findByRole("button", { name: "Discover tools" });
    await discover();
    await selectTool("/mcp set_object_semantics");
    typeArguments(ARGUMENTS);
    run("/mcp set_object_semantics");
    confirmWrite();
    expect(callPosts()).toHaveLength(1);
    const signal = callSignal();

    fireEvent.change(screen.getByLabelText("Personal access token"), { target: { value: `${PAT}-replaced` } });
    expect(signal.aborted).toBe(true);
    expect(screen.queryByText(/belongs to the signed-in user/)).toBeNull();
    expect(screen.queryByRole("listitem")).toBeNull();
    expect(screen.queryByRole("textbox", { name: "Arguments" })).toBeNull();
    expect(screen.queryByRole("dialog")).toBeNull();
    expect(screen.queryByRole("region", { name: UNKNOWN })).toBeNull();
    expect(screen.queryByText(CANCELLATION)).toBeNull();
    expect(screen.queryByText(STOPPED)).toBeNull();

    await act(async () => {
      release(jsonResponse(200, callEnvelope(1, JSON.stringify({ rows: ["stale-pat-marker"] }))));
    });
    expect(document.body.textContent).not.toContain("stale-pat-marker");
    expect(screen.queryByRole("region", { name: UNKNOWN })).toBeNull();
    expect(screen.queryByText(CANCELLATION)).toBeNull();
    expect(screen.queryByRole("region", { name: "Tool result" })).toBeNull();
    expect((screen.getByLabelText("Personal access token") as HTMLInputElement).value).toBe(`${PAT}-replaced`);
  });

  it("clears the User PAT and in-memory results when leaving or restoring a persisted page", async () => {
    let release: (response: Response) => void = () => {};
    callResponder = (_url, body) =>
      jsonResponse(200, callEnvelope(body.id, JSON.stringify({ rows: ["memory-marker"] })));
    const view = await readyWrite();
    await selectTool("/mcp run_sql");
    typeArguments('{"statement":"select 1"}');
    run("/mcp run_sql");
    expect((await screen.findByRole("region", { name: "Tool result" })).textContent).toContain(
      "memory-marker",
    );

    act(() => {
      window.dispatchEvent(new PageTransitionEvent("pageshow", { persisted: true }));
    });
    expect((screen.getByLabelText("Personal access token") as HTMLInputElement).value).toBe("");
    expect(document.body.textContent).not.toContain("memory-marker");
    expect(screen.queryByRole("region", { name: UNKNOWN })).toBeNull();
    expect(screen.queryByText(/belongs to the signed-in user/)).toBeNull();
    expect(storageDump(localStorage)).not.toContain(PAT);
    expect(storageDump(sessionStorage)).not.toContain(PAT);

    callResponder = () =>
      new Promise<Response>((resolve) => {
        release = resolve;
      });
    verifyPat();
    await screen.findByRole("button", { name: "Discover tools" });
    await discover();
    await selectTool("/mcp set_object_semantics");
    typeArguments(ARGUMENTS);
    run("/mcp set_object_semantics");
    confirmWrite();
    expect(callPosts()).toHaveLength(2);
    const signal = callSignal(1);

    view.unmount();
    expect(signal.aborted).toBe(true);
    await act(async () => {
      release(jsonResponse(200, callEnvelope(1, JSON.stringify({ rows: ["stale-leave-marker"] }))));
    });

    await renderMetadata();
    expect((screen.getByLabelText("Personal access token") as HTMLInputElement).value).toBe("");
    expect(document.body.textContent).not.toContain("stale-leave-marker");
    expect(document.body.textContent).not.toContain("memory-marker");
    expect(screen.queryByRole("region", { name: UNKNOWN })).toBeNull();
    expect(screen.queryByText(CANCELLATION)).toBeNull();
    expect(screen.queryByRole("button", { name: "Discover tools" })).toBeNull();
  });

  it("drops an in-flight request when the endpoint changes", async () => {
    let release: (response: Response) => void = () => {};
    callResponder = () =>
      new Promise<Response>((resolve) => {
        release = resolve;
      });
    const view = await readyWrite();
    run("/mcp set_object_semantics");
    confirmWrite();
    expect(callPosts()).toHaveLength(1);
    const signal = callSignal();

    pathname.current = "/console/mcp/entity";
    const { default: Layout } = await import("@/app/console/mcp/layout");
    const { McpEntityDetail } = await import("@/features/mcp/McpEntityDetail");
    view.rerender(shell(createElement(Layout, null, createElement(McpEntityDetail))));
    expect(await screen.findByText("Selected endpoint /mcp/entity")).toBeTruthy();
    await act(async () => {});
    expect(signal.aborted).toBe(true);
    expect((screen.getByLabelText("Personal access token") as HTMLInputElement).value).toBe(PAT);

    await act(async () => {
      release(jsonResponse(200, callEnvelope(1, JSON.stringify({ rows: ["stale-endpoint-marker"] }))));
    });
    expect(document.body.textContent).not.toContain("stale-endpoint-marker");
    expect(screen.queryByRole("region", { name: UNKNOWN })).toBeNull();
    expect(screen.queryByText(CANCELLATION)).toBeNull();
    expect(screen.queryByText(STOPPED)).toBeNull();
    expect(callPosts()).toHaveLength(1);
  });

  it("explains the existing server record beside run and does not save or download the result", async () => {
    const writes: string[] = [];
    const original = Storage.prototype.setItem;
    vi.spyOn(Storage.prototype, "setItem").mockImplementation(function setItem(
      this: Storage,
      key: string,
      value: string,
    ) {
      writes.push(`${key}=${value}`);
      return original.call(this, key, value);
    });
    const opens = vi.fn();
    vi.stubGlobal("indexedDB", { open: opens });
    await readyWrite();
    await selectTool("/mcp run_sql");
    const region = screen.getByRole("region", { name: "Arguments for /mcp run_sql" });
    expect(within(region).getByRole("button", { name: "Run /mcp run_sql" })).toBeTruthy();
    const note = region.textContent ?? "";
    expect(note).toContain("semantics.object_patch");
    expect(note).toContain("semantics.column_patch");
    expect(note).toContain("join.create");
    expect(note).toContain("join.patch");
    expect(note).toContain("join.reject");
    expect(note).toContain("join.restore");
    expect(note).toContain("join.delete");
    expect(note).toContain("query.run");
    expect(note).toContain("sql_sha256");
    expect(note).toContain("sql_summary");
    expect(note).toContain("entity access log");
    expect(note).toContain("resolve_pat_bearer");
    expect(note).toContain("user_pats.last_used_at");
    expect(note).toContain("GET /auth/me");
    expect(note).toContain("no call history");
    expect(note).toContain("not the absence of a server record");
    expect(note).not.toMatch(FALSE_PROMISE);
    expect(note).not.toMatch(/idempotency|retention period/i);

    typeArguments('{"statement":"select 1"}');
    run("/mcp run_sql");
    expect((await screen.findByRole("region", { name: "Tool result" })).textContent).toContain(
      "write-result",
    );
    const stored = writes.join("\n");
    expect(stored).not.toContain(PAT);
    expect(stored).not.toContain("select 1");
    expect(stored).not.toContain("write-result");
    expect(opens).not.toHaveBeenCalled();
    expect(document.querySelector("a[download]")).toBeNull();
    expect(screen.queryByRole("button", { name: /download|export/i })).toBeNull();
    expect(window.location.search).toBe("");
  });
});
