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
