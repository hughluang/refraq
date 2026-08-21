const DEFAULT_FROM = "/console";

function hasControlChar(value: string): boolean {
  for (const char of value) {
    const code = char.codePointAt(0) ?? 0;
    if (code < 32 || code === 127) return true;
  }
  return false;
}

function percentDecoded(value: string): string | null {
  try {
    return decodeURIComponent(value);
  } catch {
    return null;
  }
}

/**
 * Validate same-origin relative return paths used by the `from` query param.
 *
 * Mirrors backend `safe_from`. Browsers normalize a backslash to a slash while
 * resolving, so `/\evil.example` would leave the Console origin; raw and
 * percent-decoded forms are both rejected.
 */
export function resolveFromPath(raw: string | null | undefined): string {
  if (!raw) return DEFAULT_FROM;
  if (!raw.startsWith("/") || hasControlChar(raw)) return DEFAULT_FROM;
  if (raw === "/") return "/";
  if (raw[1] === "/" || raw[1] === "\\") return DEFAULT_FROM;
  const decoded = percentDecoded(raw);
  if (decoded === null || hasControlChar(decoded)) return DEFAULT_FROM;
  if (raw.includes("\\") || decoded.includes("\\")) return DEFAULT_FROM;
  if (raw.includes("#") || decoded.startsWith("//")) return DEFAULT_FROM;
  return raw;
}

/** Build `/login?from=...` for the current browser location (client-only). */
export function loginRedirectWithFrom(): string {
  if (typeof window === "undefined") {
    return "/login";
  }
  if (window.location.pathname.startsWith("/login")) {
    return "/login";
  }
  const path = `${window.location.pathname}${window.location.search}`;
  const from = resolveFromPath(path);
  return `/login?from=${encodeURIComponent(from)}`;
}
