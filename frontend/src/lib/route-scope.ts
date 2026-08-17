const PROTECTED_PREFIXES = ["/console"];

/** True for Management Console documents that may fetch Session identity. */
export function isProtectedPath(pathname: string): boolean {
  return PROTECTED_PREFIXES.some(
    (prefix) => pathname === prefix || pathname.startsWith(`${prefix}/`),
  );
}
