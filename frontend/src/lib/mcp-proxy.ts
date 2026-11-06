/** Same-origin MCP proxies: stream to the MCP process, never expose readyz. */

const TIMEOUT_MARGIN_SEC = 5;

type McpUpstreamSpec = {
  envName: "REFRAQ_MCP_UPSTREAM" | "REFRAQ_ENTITY_MCP_UPSTREAM";
  defaultOrigin: string;
  path: string;
  queryTimeoutSec: number;
};

const METADATA_UPSTREAM: McpUpstreamSpec = {
  envName: "REFRAQ_MCP_UPSTREAM",
  defaultOrigin: "http://127.0.0.1:8001",
  path: "/mcp",
  queryTimeoutSec: 3600,
};

const ENTITY_UPSTREAM: McpUpstreamSpec = {
  envName: "REFRAQ_ENTITY_MCP_UPSTREAM",
  defaultOrigin: "http://127.0.0.1:8002",
  path: "/mcp/entity",
  queryTimeoutSec: 300,
};

export function isMcpPassthroughPath(pathname: string): boolean {
  return pathname === "/mcp" || pathname.startsWith("/mcp/");
}

function upstreamOrigin(
  spec: McpUpstreamSpec,
  env: NodeJS.ProcessEnv,
): string {
  const raw = env[spec.envName] || spec.defaultOrigin;
  return raw.replace(/\/$/, "");
}

function upstreamUrl(
  spec: McpUpstreamSpec,
  requestUrl: string,
  env: NodeJS.ProcessEnv,
): string {
  const incoming = new URL(requestUrl);
  return `${upstreamOrigin(spec, env)}${spec.path}${incoming.search}`;
}

function proxyTimeoutMs(spec: McpUpstreamSpec): number {
  return (spec.queryTimeoutSec + TIMEOUT_MARGIN_SEC) * 1000;
}

export function mcpProxyTimeoutMs(): number {
  return proxyTimeoutMs(METADATA_UPSTREAM);
}

export function mcpUpstreamUrl(
  requestUrl: string,
  env: NodeJS.ProcessEnv = process.env,
): string {
  return upstreamUrl(METADATA_UPSTREAM, requestUrl, env);
}

export function entityMcpProxyTimeoutMs(): number {
  return proxyTimeoutMs(ENTITY_UPSTREAM);
}

export function entityMcpUpstreamUrl(
  requestUrl: string,
  env: NodeJS.ProcessEnv = process.env,
): string {
  return upstreamUrl(ENTITY_UPSTREAM, requestUrl, env);
}

export type McpProxyRequest = {
  url: string;
  method: string;
  headers: Headers;
  body: ReadableStream<Uint8Array> | null;
};

/** POST the Console request to one MCP upstream and stream the body back. */
export async function proxyMcpPost(
  request: McpProxyRequest,
  target: string,
  timeoutMs: number,
): Promise<Response> {
  const startedAtMs = Date.now();
  const headers = new Headers(request.headers);
  headers.delete("host");
  headers.delete("connection");
  headers.delete("content-length");
  headers.delete("transfer-encoding");
  const method = request.method.toUpperCase();
  const init: RequestInit & { duplex?: "half" } = {
    method,
    headers,
    redirect: "manual",
    signal: AbortSignal.timeout(timeoutMs),
  };
  init.body = request.body;
  init.duplex = "half";
  try {
    const upstream = await fetch(target, init);
    const out = new Headers(upstream.headers);
    out.set("X-Accel-Buffering", "no");
    return new Response(
      guardProxiedBody(
        upstream.body,
        {
          method,
          path: new URL(request.url).pathname,
          startedAtMs,
        },
        console.warn,
      ),
      {
        status: upstream.status,
        statusText: upstream.statusText,
        headers: out,
      },
    );
  } catch {
    return new Response(JSON.stringify({ error: "mcp_upstream_unavailable" }), {
      status: 502,
      headers: {
        "content-type": "application/json",
        "X-Accel-Buffering": "no",
      },
    });
  }
}

export type ProxiedBodyMeta = {
  method: string;
  path: string;
  startedAtMs: number;
};

/**
 * Copy the upstream body. A read failure rejects the readable after one log
 * line. A write failure cancels the upstream after one log line.
 */
export function guardProxiedBody(
  body: ReadableStream<Uint8Array> | null,
  meta: ProxiedBodyMeta,
  warn: (message: string) => void,
): ReadableStream<Uint8Array> | null {
  if (body == null) return null;
  const transform = new TransformStream<Uint8Array, Uint8Array>();
  const writer = transform.writable.getWriter();
  const reader = body.getReader();

  const report = (error: unknown) => {
    const name = error instanceof Error ? error.name : "Error";
    const elapsedMs = Date.now() - meta.startedAtMs;
    warn(
      `mcp proxy body aborted method=${meta.method} path=${meta.path} elapsed_ms=${elapsedMs} error=${name}`,
    );
  };

  const pump = async () => {
    for (;;) {
      let next: ReadableStreamReadResult<Uint8Array>;
      try {
        next = await reader.read();
      } catch (error) {
        report(error);
        await writer.abort(error);
        return;
      }
      if (next.done) {
        await writer.close();
        return;
      }
      try {
        await writer.write(next.value);
      } catch (error) {
        report(error);
        await reader.cancel();
        return;
      }
    }
  };
  void pump();
  return transform.readable;
}
