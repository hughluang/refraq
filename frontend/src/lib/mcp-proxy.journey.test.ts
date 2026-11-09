import { execFileSync, spawn, type ChildProcess } from "node:child_process";
import path from "node:path";
import { fileURLToPath } from "node:url";

import { afterAll, describe, expect, it } from "vitest";

import { proxyMcpPost } from "@/lib/mcp-proxy";

/**
 * Public same-origin proxy journey against real memory MCP hosts.
 * This is not a PostgreSQL access-enforcement run.
 */

const PROTOCOL_VERSION = "2026-07-28";
const PUBLIC_ORIGIN = "http://127.0.0.1:3000";
const REPO_ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "../../..");
const PYTHON = path.join(REPO_ROOT, ".venv/bin/python");
const HOST_SCRIPT = path.join(REPO_ROOT, "backend/tests/mcp_proxy_journey_host.py");
const LIST_ID = 1;
const CALL_ID = 2;

type JsonRpc = Record<string, unknown>;

type ListedTool = {
  name: string;
  inputSchema?: unknown;
  _meta?: Record<string, unknown>;
};

type HostReady = {
  domain: "metadata" | "entity";
  port: number;
  secret: string;
  store: string;
  mcp_version: string;
  protocol_version: string;
};

type RunningHost = HostReady & {
  child: ChildProcess;
  output: () => string;
};

type Forwarded = {
  url: string;
  origin: string | null;
  protocolVersion: string | null;
  method: string | null;
  name: string | null;
  session: string | null;
  hasBearer: boolean;
};

const children = new Set<ChildProcess>();
const nativeFetch = globalThis.fetch.bind(globalThis);

afterAll(async () => {
  await Promise.all([...children].map((child) => stopHost(child)));
});

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function importedMcpVersion(): string {
  return execFileSync(
    PYTHON,
    ["-c", "import importlib.metadata as m; print(m.version('mcp'))"],
    { cwd: REPO_ROOT, encoding: "utf8" },
  ).trim();
}

async function readBody(response: Response): Promise<string> {
  if (!response.body) return response.text();
  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let body = "";
  for (;;) {
    let next: ReadableStreamReadResult<Uint8Array>;
    try {
      next = await reader.read();
    } catch (error) {
      const message = error instanceof Error ? error.message : String(error);
      throw new Error(`malformed MCP stream chunk (not an empty tool list): ${message}`);
    }
    if (next.done) break;
    body += decoder.decode(next.value, { stream: true });
  }
  body += decoder.decode();
  return body;
}

function messageFromSse(body: string, id: number): JsonRpc {
  const normalized = body.replace(/\r\n/g, "\n").replace(/\r/g, "\n");
  if (!normalized.endsWith("\n\n")) {
    throw new Error(
      "malformed MCP SSE stream is truncated (not an empty tool list)",
    );
  }
  let matched: JsonRpc | null = null;
  for (const frame of normalized.split("\n\n")) {
    if (frame.trim().length === 0) continue;
    const dataLines: string[] = [];
    for (const line of frame.split("\n")) {
      if (line.length === 0 || line.startsWith(":")) continue;
      if (line.startsWith("data:")) {
        const value = line.slice("data:".length);
        dataLines.push(value.startsWith(" ") ? value.slice(1) : value);
        continue;
      }
      if (
        line.startsWith("event:") ||
        line.startsWith("id:") ||
        line.startsWith("retry:")
      ) {
        continue;
      }
      throw new Error(
        "malformed MCP SSE stream has an unexpected line (not an empty tool list)",
      );
    }
    if (dataLines.length === 0) continue;
    let message: unknown;
    try {
      message = JSON.parse(dataLines.join("\n"));
    } catch (error) {
      const detail = error instanceof Error ? error.message : String(error);
      throw new Error(
        `malformed MCP SSE chunk (not an empty tool list): ${detail}`,
      );
    }
    if (!isRecord(message) || message.jsonrpc !== "2.0") {
      throw new Error(
        "malformed MCP SSE chunk is not a JSON-RPC object (not an empty tool list)",
      );
    }
    if (message.id !== id) continue;
    matched = message;
  }
  if (matched == null) {
    throw new Error(
      `malformed MCP SSE stream has no frame for id ${id} (not an empty tool list)`,
    );
  }
  return matched;
}

/** Journey reader. A broken stream throws; it does not become an empty tool list. */
async function readProxiedJsonRpc(
  response: Response,
  id: number,
): Promise<JsonRpc> {
  const body = await readBody(response);
  const contentType = response.headers.get("content-type") ?? "";
  if (
    contentType.includes("text/event-stream") ||
    body.startsWith("event:") ||
    body.startsWith("data:")
  ) {
    return messageFromSse(body, id);
  }
  let message: unknown;
  try {
    message = JSON.parse(body);
  } catch (error) {
    const detail = error instanceof Error ? error.message : String(error);
    throw new Error(`malformed MCP JSON body (not an empty tool list): ${detail}`);
  }
  if (!isRecord(message) || message.jsonrpc !== "2.0" || message.id !== id) {
    throw new Error(
      `malformed MCP JSON body does not match id ${id} (not an empty tool list)`,
    );
  }
  return message;
}

function listedTools(message: JsonRpc): unknown[] {
  if (message.error != null) {
    throw new Error(
      `tools/list returned a protocol error (not an empty tool list): ${JSON.stringify(message.error)}`,
    );
  }
  const result = message.result;
  if (!isRecord(result) || !Array.isArray(result.tools)) {
    throw new Error(
      "tools/list result has no tools array (not an empty tool list)",
    );
  }
  return result.tools;
}

function isReadTool(value: unknown): value is ListedTool {
  if (!isRecord(value) || typeof value.name !== "string" || value.name.length === 0) {
    return false;
  }
  const meta = value._meta;
  return isRecord(meta) && meta["io.refraq/execution"] === "read";
}

function requiredFields(tool: ListedTool): string[] {
  if (!isRecord(tool.inputSchema) || !Array.isArray(tool.inputSchema.required)) {
    return [];
  }
  return tool.inputSchema.required.filter(
    (item): item is string => typeof item === "string",
  );
}

function selectReadTool(tools: unknown[]): ListedTool {
  const reads = tools.filter(isReadTool);
  if (reads.length === 0) {
    throw new Error(
      'tools/list published no tool with _meta["io.refraq/execution"] === "read"',
    );
  }
  return reads.find((tool) => requiredFields(tool).length === 0) ?? reads[0];
}

function requestMeta(): Record<string, unknown> {
  return {
    "io.modelcontextprotocol/protocolVersion": PROTOCOL_VERSION,
    "io.modelcontextprotocol/clientCapabilities": {},
  };
}

function protocolHeaders(
  pat: string,
  method: "tools/list" | "tools/call",
  toolName?: string,
): Headers {
  const headers = new Headers({
    Accept: "application/json, text/event-stream",
    "Content-Type": "application/json",
    Authorization: `Bearer ${pat}`,
    Origin: PUBLIC_ORIGIN,
    "mcp-protocol-version": PROTOCOL_VERSION,
    "mcp-method": method,
  });
  if (toolName !== undefined) headers.set("mcp-name", toolName);
  return headers;
}

function jsonStream(value: unknown): ReadableStream<Uint8Array> {
  const bytes = new TextEncoder().encode(JSON.stringify(value));
  return new ReadableStream({
    start(controller) {
      controller.enqueue(bytes);
      controller.close();
    },
  });
}

function installForwardCapture(): {
  records: Forwarded[];
  restore: () => void;
} {
  const records: Forwarded[] = [];
  const original = globalThis.fetch;
  globalThis.fetch = (async (input: RequestInfo | URL, init?: RequestInit) => {
    const headers = new Headers(init?.headers);
    const url =
      typeof input === "string"
        ? input
        : input instanceof URL
          ? input.toString()
          : input.url;
    records.push({
      url,
      origin: headers.get("origin"),
      protocolVersion: headers.get("mcp-protocol-version"),
      method: headers.get("mcp-method"),
      name: headers.get("mcp-name"),
      session: headers.get("mcp-session-id"),
      hasBearer: (headers.get("authorization") ?? "").startsWith("Bearer "),
    });
    return original(input, init);
  }) as typeof fetch;
  return {
    records,
    restore: () => {
      globalThis.fetch = original;
    },
  };
}

async function postThroughProxy(
  host: RunningHost,
  publicPath: "/mcp" | "/mcp/entity",
  id: number,
  method: "tools/list" | "tools/call",
  params: Record<string, unknown>,
  toolName: string | undefined,
  records: Forwarded[],
): Promise<Response> {
  const upstream = `http://127.0.0.1:${host.port}${publicPath}`;
  const response = await proxyMcpPost(
    {
      url: `${PUBLIC_ORIGIN}${publicPath}`,
      method: "POST",
      headers: protocolHeaders(host.secret, method, toolName),
      body: jsonStream({
        jsonrpc: "2.0",
        id,
        method,
        params,
      }),
    },
    upstream,
    20_000,
  );
  const forwarded = records[records.length - 1];
  expect(forwarded?.url).toBe(upstream);
  expect(forwarded?.origin).toBe(PUBLIC_ORIGIN);
  expect(forwarded?.protocolVersion).toBe(PROTOCOL_VERSION);
  expect(forwarded?.method).toBe(method);
  expect(forwarded?.session).toBeNull();
  expect(forwarded?.hasBearer).toBe(true);
  expect(forwarded?.name).toBe(method === "tools/call" ? toolName : null);
  return response;
}

async function readSuccess(response: Response, id: number): Promise<JsonRpc> {
  if (response.status !== 200) {
    const text = await response.text();
    throw new Error(`MCP proxy status ${response.status}: ${text.slice(0, 400)}`);
  }
  return readProxiedJsonRpc(response, id);
}

function assertCompletedRoundTrip(message: JsonRpc, id: number): void {
  expect(message.jsonrpc).toBe("2.0");
  expect(message.id).toBe(id);
  // Empty data and a domain error envelope are both a completed tool result.
  expect(Object.prototype.hasOwnProperty.call(message, "result")).toBe(true);
}

async function waitForForwardedOrigin(host: RunningHost, count: number): Promise<void> {
  const expected = `JOURNEY_ORIGIN ${PUBLIC_ORIGIN}`;
  const deadline = Date.now() + 5_000;
  while (Date.now() < deadline) {
    const lines = host
      .output()
      .split("\n")
      .filter((line) => line.startsWith("JOURNEY_ORIGIN "));
    if (lines.length >= count) {
      expect(lines.slice(0, count)).toEqual(Array.from({ length: count }, () => expected));
      return;
    }
    await new Promise((resolve) => setTimeout(resolve, 20));
  }
  throw new Error(
    `memory host ${host.domain} did not observe Origin ${PUBLIC_ORIGIN} on the wire`,
  );
}

function startHost(
  domain: "metadata" | "entity",
  secret?: string,
): Promise<RunningHost> {
  const env = { ...process.env };
  delete env.REFRAQ_JOURNEY_PAT_SECRET;
  if (secret !== undefined) env.REFRAQ_JOURNEY_PAT_SECRET = secret;
  const child = spawn(PYTHON, [HOST_SCRIPT, domain], {
    cwd: REPO_ROOT,
    env,
    stdio: ["ignore", "pipe", "pipe"],
  });
  children.add(child);
  child.stdout?.setEncoding("utf8");
  child.stderr?.setEncoding("utf8");

  return new Promise((resolve, reject) => {
    let stdout = "";
    let stderr = "";
    let settled = false;
    const timer = setTimeout(() => {
      if (settled) return;
      settled = true;
      child.kill("SIGKILL");
      reject(
        new Error(
          `memory host ${domain} did not become ready\n${stderr.slice(-4000)}`,
        ),
      );
    }, 90_000);
    const finish = (error: Error) => {
      if (settled) return;
      settled = true;
      clearTimeout(timer);
      reject(error);
    };
    child.stdout?.on("data", (chunk: string) => {
      stdout += chunk;
      const line = stdout
        .split("\n")
        .find((item) => item.startsWith("JOURNEY_READY "));
      if (!line || settled) return;
      settled = true;
      clearTimeout(timer);
      const ready = JSON.parse(line.slice("JOURNEY_READY ".length)) as HostReady;
      resolve({
        ...ready,
        child,
        output: () => stdout,
      });
    });
    child.stderr?.on("data", (chunk: string) => {
      stderr += chunk;
    });
    child.once("error", (error) => {
      finish(error);
    });
    child.once("exit", (code) => {
      finish(
        new Error(
          `memory host ${domain} exited ${code ?? "null"} before ready\n${stderr.slice(-4000)}`,
        ),
      );
    });
  });
}

async function stopHost(child: ChildProcess): Promise<void> {
  children.delete(child);
  if (child.exitCode != null || child.signalCode != null) return;
  child.kill("SIGTERM");
  await new Promise<void>((resolve) => {
    const timer = setTimeout(() => {
      if (child.exitCode == null && child.signalCode == null) child.kill("SIGKILL");
    }, 2_000);
    child.once("exit", () => {
      clearTimeout(timer);
      resolve();
    });
  });
}

async function assertMemoryReady(host: RunningHost): Promise<void> {
  const response = await nativeFetch(`http://127.0.0.1:${host.port}/readyz`);
  expect(response.status).toBe(200);
  expect(await response.json()).toEqual({ status: "ready", backend: "memory" });
}

async function listThroughProxy(
  host: RunningHost,
  publicPath: "/mcp" | "/mcp/entity",
  records: Forwarded[],
): Promise<ListedTool> {
  const response = await postThroughProxy(
    host,
    publicPath,
    LIST_ID,
    "tools/list",
    { _meta: requestMeta() },
    undefined,
    records,
  );
  const message = await readSuccess(response, LIST_ID);
  const tool = selectReadTool(listedTools(message));
  expect(tool._meta?.["io.refraq/execution"]).toBe("read");
  return tool;
}

describe("public proxy journey reader", () => {
  it("reads JSON and the SSE frame with the request id", async () => {
    const json = await readProxiedJsonRpc(
      new Response(
        JSON.stringify({
          jsonrpc: "2.0",
          id: LIST_ID,
          result: { tools: [{ name: "listed-read" }] },
        }),
        { headers: { "content-type": "application/json" } },
      ),
      LIST_ID,
    );
    expect(listedTools(json)).toEqual([{ name: "listed-read" }]);

    const sse = [
      'data: {"jsonrpc":"2.0","id":9,"result":{"tools":[]}}',
      "",
      'data: {"jsonrpc":"2.0","id":1,"result":{"tools":[{"name":"listed-read"}]}}',
      "",
      "",
    ].join("\n");
    const streamed = await readProxiedJsonRpc(
      new Response(sse, { headers: { "content-type": "text/event-stream" } }),
      LIST_ID,
    );
    expect(listedTools(streamed)).toEqual([{ name: "listed-read" }]);
  });

  it("fails a broken or unmatched stream instead of an empty tool list", async () => {
    await expect(
      readProxiedJsonRpc(
        new Response("{", { headers: { "content-type": "application/json" } }),
        LIST_ID,
      ),
    ).rejects.toThrow(/not an empty tool list/);

    await expect(
      readProxiedJsonRpc(
        new Response(
          'data: {"jsonrpc":"2.0","id":1,"result":{"tools":\n\n',
          { headers: { "content-type": "text/event-stream" } },
        ),
        LIST_ID,
      ),
    ).rejects.toThrow(/not an empty tool list/);

    const otherId = [
      'data: {"jsonrpc":"2.0","id":9,"result":{"tools":[]}}',
      "",
      "",
    ].join("\n");
    await expect(
      readProxiedJsonRpc(
        new Response(otherId, { headers: { "content-type": "text/event-stream" } }),
        LIST_ID,
      ),
    ).rejects.toThrow(/not an empty tool list/);

    const interrupted = new Response(
      new ReadableStream({
        start(controller) {
          controller.enqueue(
            new TextEncoder().encode('data: {"jsonrpc":"2.0","id":1'),
          );
          controller.error(new Error("upstream chunk failed"));
        },
      }),
      { headers: { "content-type": "text/event-stream" } },
    );
    await expect(readProxiedJsonRpc(interrupted, LIST_ID)).rejects.toThrow(
      /not an empty tool list/,
    );
  });
});

describe("public proxy to real memory MCP hosts", () => {
  it("sends tools/list and one read tools/call through the proxy", async () => {
    const mcpVersion = importedMcpVersion();
    const metadata = await startHost("metadata");
    const entity = await startHost("entity", metadata.secret);
    const capture = installForwardCapture();
    try {
      expect(metadata.store).toBe("memory");
      expect(entity.store).toBe("memory");
      expect(metadata.protocol_version).toBe(PROTOCOL_VERSION);
      expect(entity.protocol_version).toBe(PROTOCOL_VERSION);
      expect(metadata.mcp_version).toBe(mcpVersion);
      expect(entity.mcp_version).toBe(mcpVersion);
      expect(metadata.secret.startsWith("rfq_pat_")).toBe(true);
      expect(entity.secret).toBe(metadata.secret);
      await assertMemoryReady(metadata);
      await assertMemoryReady(entity);

      const evidence =
        `memory host (not a PostgreSQL access-enforcement run); ` +
        `imported mcp ${mcpVersion}; protocol ${PROTOCOL_VERSION}`;
      console.info(evidence);

      for (const [host, publicPath] of [
        [metadata, "/mcp"],
        [entity, "/mcp/entity"],
      ] as const) {
        const tool = await listThroughProxy(host, publicPath, capture.records);
        const call = await postThroughProxy(
          host,
          publicPath,
          CALL_ID,
          "tools/call",
          {
            name: tool.name,
            arguments: {},
            _meta: requestMeta(),
          },
          tool.name,
          capture.records,
        );
        const message = await readSuccess(call, CALL_ID);
        assertCompletedRoundTrip(message, CALL_ID);
        await waitForForwardedOrigin(host, 2);
        console.info(
          `${evidence}; domain=${host.domain}; path=${publicPath}; read tool=${tool.name}`,
        );
      }

      expect(capture.records.map((record) => record.method)).toEqual([
        "tools/list",
        "tools/call",
        "tools/list",
        "tools/call",
      ]);
      expect(capture.records.map((record) => new URL(record.url).pathname)).toEqual([
        "/mcp",
        "/mcp",
        "/mcp/entity",
        "/mcp/entity",
      ]);
      expect(capture.records.some((record) => record.method === "initialize")).toBe(
        false,
      );
    } finally {
      capture.restore();
      await stopHost(metadata.child);
      await stopHost(entity.child);
    }
  }, 180_000);

  it("fails the stopped upstream without replacing the other tools/list", async () => {
    const metadata = await startHost("metadata");
    const entity = await startHost("entity", metadata.secret);
    const capture = installForwardCapture();
    try {
      await assertMemoryReady(metadata);
      await assertMemoryReady(entity);

      await stopHost(entity.child);
      const metadataTool = await listThroughProxy(metadata, "/mcp", capture.records);
      expect(metadataTool._meta?.["io.refraq/execution"]).toBe("read");
      const entityDown = await postThroughProxy(
        entity,
        "/mcp/entity",
        LIST_ID,
        "tools/list",
        { _meta: requestMeta() },
        undefined,
        capture.records,
      );
      expect(entityDown.status).toBe(502);
      expect(await entityDown.json()).toEqual({ error: "mcp_upstream_unavailable" });

      const restarted = await startHost("entity", metadata.secret);
      await assertMemoryReady(restarted);
      await stopHost(metadata.child);
      const entityTool = await listThroughProxy(
        restarted,
        "/mcp/entity",
        capture.records,
      );
      expect(entityTool._meta?.["io.refraq/execution"]).toBe("read");
      const metadataDown = await postThroughProxy(
        metadata,
        "/mcp",
        LIST_ID,
        "tools/list",
        { _meta: requestMeta() },
        undefined,
        capture.records,
      );
      expect(metadataDown.status).toBe(502);
      expect(await metadataDown.json()).toEqual({
        error: "mcp_upstream_unavailable",
      });
      await stopHost(restarted.child);
    } finally {
      capture.restore();
      await stopHost(metadata.child);
      await stopHost(entity.child);
    }
  }, 180_000);
});
