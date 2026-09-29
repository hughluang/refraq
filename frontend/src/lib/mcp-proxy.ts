/** Same-origin `/mcp` proxy: stream to the MCP process, never expose readyz. */

const QUERY_TIMEOUT_SEC_MAX = 3600;
const TIMEOUT_MARGIN_SEC = 5;
const DEFAULT_UPSTREAM = "http://127.0.0.1:8001";

export function isMcpPassthroughPath(pathname: string): boolean {
  return pathname === "/mcp" || pathname.startsWith("/mcp/");
}

export function mcpUpstreamOrigin(
  env: NodeJS.ProcessEnv = process.env,
): string {
  const raw = env.REFRAQ_MCP_UPSTREAM || DEFAULT_UPSTREAM;
  return raw.replace(/\/$/, "");
}

export function mcpProxyTimeoutMs(): number {
  return (QUERY_TIMEOUT_SEC_MAX + TIMEOUT_MARGIN_SEC) * 1000;
}

export function mcpUpstreamUrl(
  requestUrl: string,
  env: NodeJS.ProcessEnv = process.env,
): string {
  const incoming = new URL(requestUrl);
  return `${mcpUpstreamOrigin(env)}/mcp${incoming.search}`;
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
