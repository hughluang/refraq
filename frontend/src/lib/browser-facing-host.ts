const HOST_RE =
  /^(?:[A-Za-z0-9](?:[A-Za-z0-9.-]{0,251}[A-Za-z0-9])?|\[[0-9A-Fa-f:]+\])(?::\d{1,5})?$/;
const LOOPBACK = new Set(["localhost", "127.0.0.1", "::1", "0:0:0:0:0:0:0:1"]);

export function validBrowserHost(value: string): boolean {
  if (!value || value.length > 262) return false;
  for (const char of value) {
    const code = char.codePointAt(0) ?? 0;
    if (code < 32 || code === 127) return false;
  }
  return HOST_RE.test(value);
}

export function hostnameOf(host: string): string {
  if (host.startsWith("[")) {
    const end = host.indexOf("]");
    if (end === -1) return "";
    return host.slice(1, end);
  }
  if ((host.match(/:/g) ?? []).length === 1) {
    return host.slice(0, host.lastIndexOf(":"));
  }
  return host;
}

export function isLoopbackHost(host: string): boolean {
  return LOOPBACK.has(hostnameOf(host).toLowerCase());
}

/**
 * Host stamped onto `/api` as `X-Forwarded-Host` for OIDC callback origin.
 *
 * Configured `REFRAQ_BROWSER_FACING_HOST` always wins. Otherwise only a
 * loopback request Host is used; client-supplied public Hosts are dropped.
 */
export function browserFacingHostFromEnv(
  env: Record<string, string | undefined> = process.env,
  requestHost: string | null = null,
): string | null {
  const configured = env.REFRAQ_BROWSER_FACING_HOST?.trim() ?? "";
  if (configured) {
    return validBrowserHost(configured) ? configured : null;
  }
  const raw = requestHost?.split(",")[0]?.trim() ?? "";
  if (validBrowserHost(raw) && isLoopbackHost(raw)) {
    return raw;
  }
  return null;
}
