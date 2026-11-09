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

function fromRpc(message: unknown, id: number): McpToolsListResult | "skip" {
  if (typeof message !== "object" || message === null || Array.isArray(message)) {
    return { status: "transport-failure" };
  }
  const record = message as Record<string, unknown>;
  if (record.jsonrpc !== "2.0") return { status: "transport-failure" };
  if (record.id !== id) return "skip";
  if ("error" in record && record.error != null) return { status: "protocol-error" };
  const result = record.result;
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

function parseSse(body: string, id: number): McpToolsListResult {
  const normalized = body.replace(/\r\n/g, "\n").replace(/\r/g, "\n");
  if (!normalized.endsWith("\n\n")) return { status: "transport-failure" };
  let matched: McpToolsListResult | null = null;
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
    const parsed = fromRpc(message, id);
    if (parsed === "skip") continue;
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

/** One tools/list POST to a fixed same-origin endpoint. No tools/call. */
export async function requestToolsList(
  endpoint: string,
  pat: string,
): Promise<McpToolsListResult> {
  if (!ENDPOINTS.has(endpoint)) return { status: "unavailable" };
  const id = nextRequestId;
  nextRequestId += 1;
  let response: Response;
  try {
    response = await fetch(`${window.location.origin}${endpoint}`, {
      method: "POST",
      credentials: "omit",
      headers: {
        Accept: "application/json, text/event-stream",
        "Content-Type": "application/json",
        Authorization: `Bearer ${pat}`,
        "mcp-protocol-version": PROTOCOL_VERSION,
        "mcp-method": "tools/list",
      },
      body: JSON.stringify({
        jsonrpc: "2.0",
        id,
        method: "tools/list",
        params: {
          _meta: {
            [PROTOCOL_VERSION_META]: PROTOCOL_VERSION,
            [CLIENT_CAPABILITIES_META]: {},
          },
        },
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

  const contentType = response.headers.get("content-type") ?? "";
  if (contentType.includes("text/event-stream")) {
    const parsed = parseSse(text, id);
    // Failed HTTP must not surface a ready or empty catalog. Protocol errors stay.
    if (!response.ok && (parsed.status === "ready" || parsed.status === "empty")) {
      return { status: "unavailable" };
    }
    return parsed;
  }

  if (contentType.includes("application/json")) {
    let message: unknown;
    try {
      message = JSON.parse(text);
    } catch {
      return { status: "transport-failure" };
    }
    const parsed = fromRpc(message, id);
    if (parsed !== "skip" && parsed.status === "protocol-error") return parsed;
    if (!response.ok) return { status: "unavailable" };
    if (parsed === "skip") return { status: "transport-failure" };
    return parsed;
  }

  if (!response.ok) return { status: "unavailable" };
  return { status: "transport-failure" };
}
