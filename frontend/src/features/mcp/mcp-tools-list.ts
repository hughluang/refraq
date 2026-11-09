const PROTOCOL_VERSION = "2026-07-28";
const PROTOCOL_VERSION_META = "io.modelcontextprotocol/protocolVersion";
const CLIENT_CAPABILITIES_META = "io.modelcontextprotocol/clientCapabilities";
const EXECUTION_META = "io.refraq/execution";

const ENDPOINTS = new Set(["/mcp", "/mcp/entity"]);

let nextRequestId = 1;

export type McpListedTool = {
  name: string;
  description: string;
  inputSchema: unknown | null;
  execution: string | null;
};

export type McpToolsListResult =
  | { status: "empty" }
  | { status: "ready"; tools: McpListedTool[] }
  | { status: "unavailable" }
  | { status: "protocol-error" }
  | { status: "transport-failure" };

export type McpCallPart =
  | { kind: "text"; text: string }
  | { kind: "json"; value: unknown };

export type McpCallOutcome =
  | { status: "http" }
  | { status: "transport" }
  | { status: "protocol"; error: unknown }
  | { status: "sdk"; parts: McpCallPart[]; protocol: unknown }
  | { status: "domain"; parts: McpCallPart[]; protocol: unknown }
  | { status: "result"; parts: McpCallPart[]; protocol: unknown };

type Classified =
  | { status: "unavailable" }
  | { status: "transport-failure" }
  | { status: "protocol-error"; error: unknown }
  | { status: "result"; result: unknown };

type Envelope =
  | { status: "transport-failure" }
  | { status: "protocol-error"; error: unknown }
  | { status: "result"; result: unknown }
  | { status: "skip" };

function executionClass(tool: Record<string, unknown>): string | null {
  const meta = tool._meta;
  if (typeof meta !== "object" || meta === null || Array.isArray(meta)) return null;
  const value = (meta as Record<string, unknown>)[EXECUTION_META];
  if (typeof value !== "string" || value.length === 0) return null;
  return value;
}

function readTool(value: unknown): McpListedTool | null {
  if (typeof value !== "object" || value === null || Array.isArray(value)) return null;
  const record = value as Record<string, unknown>;
  if (typeof record.name !== "string" || record.name.length === 0) return null;
  const schema = record.inputSchema;
  return {
    name: record.name,
    description: typeof record.description === "string" ? record.description : "",
    inputSchema: schema === undefined || schema === null ? null : schema,
    execution: executionClass(record),
  };
}

function interpretTools(result: unknown): McpToolsListResult {
  if (typeof result !== "object" || result === null || Array.isArray(result)) {
    return { status: "transport-failure" };
  }
  const tools = (result as Record<string, unknown>).tools;
  if (!Array.isArray(tools)) return { status: "transport-failure" };
  if (tools.length === 0) return { status: "empty" };
  const parsed: McpListedTool[] = [];
  for (const tool of tools) {
    const item = readTool(tool);
    if (!item) return { status: "transport-failure" };
    parsed.push(item);
  }
  return { status: "ready", tools: parsed };
}

function envelopeOf(message: unknown, id: number): Envelope {
  if (typeof message !== "object" || message === null || Array.isArray(message)) {
    return { status: "transport-failure" };
  }
  const record = message as Record<string, unknown>;
  if (record.jsonrpc !== "2.0") return { status: "transport-failure" };
  if (record.id !== id) return { status: "skip" };
  if ("error" in record && record.error != null) {
    return { status: "protocol-error", error: record.error };
  }
  if (!("result" in record)) return { status: "transport-failure" };
  return { status: "result", result: record.result };
}

function parseSse(body: string, id: number): Envelope {
  const normalized = body.replace(/\r\n/g, "\n").replace(/\r/g, "\n");
  if (!normalized.endsWith("\n\n")) return { status: "transport-failure" };
  let matched: Envelope | null = null;
  for (const frame of normalized.split("\n\n")) {
    const dataLines: string[] = [];
    for (const line of frame.split("\n")) {
      if (line.length === 0 || line.startsWith(":")) continue;
      if (line.startsWith("data:")) {
        const value = line.slice("data:".length);
        dataLines.push(value.startsWith(" ") ? value.slice(1) : value);
        continue;
      }
      if (line.startsWith("event:") || line.startsWith("id:") || line.startsWith("retry:")) {
        continue;
      }
      return { status: "transport-failure" };
    }
    if (dataLines.length === 0) continue;
    let message: unknown;
    try {
      message = JSON.parse(dataLines.join("\n"));
    } catch {
      return { status: "transport-failure" };
    }
    const parsed = envelopeOf(message, id);
    if (parsed.status === "skip") continue;
    matched = parsed;
  }
  return matched ?? { status: "transport-failure" };
}

async function readBody(response: Response): Promise<string> {
  if (!response.body) return response.text();
  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let body = "";
  while (true) {
    const { done, value } = await reader.read();
    if (done) break;
    body += decoder.decode(value, { stream: true });
  }
  body += decoder.decode();
  return body;
}

function protocolHeaders(pat: string, method: string, toolName?: string): Record<string, string> {
  const headers: Record<string, string> = {
    Accept: "application/json, text/event-stream",
    "Content-Type": "application/json",
    Authorization: `Bearer ${pat}`,
    "mcp-protocol-version": PROTOCOL_VERSION,
    "mcp-method": method,
  };
  if (toolName !== undefined) headers["mcp-name"] = toolName;
  return headers;
}

function requestMeta(): Record<string, unknown> {
  return {
    [PROTOCOL_VERSION_META]: PROTOCOL_VERSION,
    [CLIENT_CAPABILITIES_META]: {},
  };
}

function classifyBody(response: Response, text: string, id: number): Classified {
  const contentType = response.headers.get("content-type") ?? "";
  if (contentType.includes("text/event-stream")) {
    const parsed = parseSse(text, id);
    if (parsed.status === "protocol-error") return parsed;
    if (parsed.status === "result" && response.ok) return parsed;
    if (parsed.status === "result") return { status: "unavailable" };
    return { status: "transport-failure" };
  }
  if (contentType.includes("application/json")) {
    let message: unknown;
    try {
      message = JSON.parse(text);
    } catch {
      return { status: "transport-failure" };
    }
    const parsed = envelopeOf(message, id);
    if (parsed.status === "protocol-error") return parsed;
    if (!response.ok) return { status: "unavailable" };
    if (parsed.status !== "result") return { status: "transport-failure" };
    return parsed;
  }
  if (!response.ok) return { status: "unavailable" };
  return { status: "transport-failure" };
}

/** Shared tools/list and tools/call POST. One header dialect, no session handshake. */
async function postMcp(
  endpoint: string,
  pat: string,
  method: "tools/list" | "tools/call",
  params: Record<string, unknown>,
  toolName?: string,
): Promise<Classified> {
  if (!ENDPOINTS.has(endpoint)) return { status: "unavailable" };
  const id = nextRequestId;
  nextRequestId += 1;
  let response: Response;
  try {
    response = await fetch(`${window.location.origin}${endpoint}`, {
      method: "POST",
      credentials: "omit",
      headers: protocolHeaders(pat, method, toolName),
      body: JSON.stringify({
        jsonrpc: "2.0",
        id,
        method,
        params,
      }),
    });
  } catch {
    return { status: "unavailable" };
  }

  if (response.status === 502) return { status: "unavailable" };

  let text: string;
  try {
    text = await readBody(response);
  } catch {
    return { status: "transport-failure" };
  }
  return classifyBody(response, text, id);
}

function textParts(result: Record<string, unknown>): string[] {
  if (!Array.isArray(result.content)) return [];
  const texts: string[] = [];
  for (const item of result.content) {
    if (typeof item !== "object" || item === null || Array.isArray(item)) continue;
    const record = item as Record<string, unknown>;
    if (record.type !== "text" || typeof record.text !== "string") continue;
    texts.push(record.text);
  }
  return texts;
}

function structuredResultText(result: Record<string, unknown>): string | null {
  const structured = result.structuredContent;
  if (typeof structured !== "object" || structured === null || Array.isArray(structured)) return null;
  const value = (structured as Record<string, unknown>).result;
  return typeof value === "string" ? value : null;
}

function domainError(text: string): boolean {
  let parsed: unknown;
  try {
    parsed = JSON.parse(text);
  } catch {
    return false;
  }
  if (typeof parsed !== "object" || parsed === null || Array.isArray(parsed)) return false;
  const error = (parsed as Record<string, unknown>).error;
  if (typeof error !== "object" || error === null || Array.isArray(error)) return false;
  const record = error as Record<string, unknown>;
  return typeof record.code === "string" && typeof record.message === "string";
}

function partFromText(text: string): McpCallPart {
  try {
    return { kind: "json", value: JSON.parse(text) };
  } catch {
    return { kind: "text", text };
  }
}

function callParts(result: Record<string, unknown>): McpCallPart[] {
  const parts: McpCallPart[] = [];
  const seen = new Set<string>();
  for (const text of textParts(result)) {
    seen.add(text);
    parts.push(partFromText(text));
  }
  const structured = structuredResultText(result);
  if (structured !== null && !seen.has(structured)) parts.push(partFromText(structured));
  return parts;
}

function interpretCall(result: unknown): McpCallOutcome {
  if (typeof result !== "object" || result === null || Array.isArray(result)) {
    return { status: "result", parts: [], protocol: result };
  }
  const record = result as Record<string, unknown>;
  const parts = callParts(record);
  if (record.isError === true) return { status: "sdk", parts, protocol: result };
  const candidates = textParts(record);
  const structured = structuredResultText(record);
  if (structured !== null) candidates.push(structured);
  if (candidates.some((text) => domainError(text))) return { status: "domain", parts, protocol: result };
  return { status: "result", parts, protocol: result };
}

function asCall(classified: Classified): McpCallOutcome {
  if (classified.status === "unavailable") return { status: "http" };
  if (classified.status === "transport-failure") return { status: "transport" };
  if (classified.status === "protocol-error") return { status: "protocol", error: classified.error };
  return interpretCall(classified.result);
}

/** One tools/list POST to a fixed same-origin endpoint. No tools/call. */
export async function requestToolsList(endpoint: string, pat: string): Promise<McpToolsListResult> {
  const classified = await postMcp(endpoint, pat, "tools/list", { _meta: requestMeta() });
  if (classified.status === "protocol-error") return { status: "protocol-error" };
  if (classified.status !== "result") return classified;
  return interpretTools(classified.result);
}

/** One explicit tools/call. The arguments value is the editor snapshot. */
export async function requestToolsCall(
  endpoint: string,
  pat: string,
  toolName: string,
  args: unknown,
): Promise<McpCallOutcome> {
  const classified = await postMcp(
    endpoint,
    pat,
    "tools/call",
    {
      name: toolName,
      arguments: args,
      _meta: requestMeta(),
    },
    toolName,
  );
  return asCall(classified);
}
