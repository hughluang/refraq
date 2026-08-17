/** Validate same-origin relative return paths used by the `from` query param. */
export function resolveFromPath(raw: string | null | undefined): string {
  if (!raw) return "/console";
  if (!raw.startsWith("/") || raw.startsWith("//")) return "/console";
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
