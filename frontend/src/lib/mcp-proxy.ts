/** Same-origin `/mcp` proxy: stream to the MCP process, never expose readyz. */

const DEFAULT_QUERY_TIMEOUT_SEC = 30;
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

export function mcpProxyTimeoutMs(
  env: NodeJS.ProcessEnv = process.env,
): number {
  const raw = env.REFRAQ_QUERY_TIMEOUT_SEC;
  if (raw === undefined) {
    return (DEFAULT_QUERY_TIMEOUT_SEC + TIMEOUT_MARGIN_SEC) * 1000;
  }
  const parsed = Number(raw);
  if (!Number.isFinite(parsed) || parsed <= 0) {
    throw new Error(
      `REFRAQ_QUERY_TIMEOUT_SEC must be a positive number, got ${JSON.stringify(raw)}`,
    );
  }
  return (parsed + TIMEOUT_MARGIN_SEC) * 1000;
}

export function mcpUpstreamUrl(
  requestUrl: string,
  env: NodeJS.ProcessEnv = process.env,
): string {
  const incoming = new URL(requestUrl);
  return `${mcpUpstreamOrigin(env)}/mcp${incoming.search}`;
}
