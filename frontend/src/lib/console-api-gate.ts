/** Console must not forward intranet process probes through `/api`. */

export function isConsoleBlockedApiPath(pathname: string): boolean {
  return pathname === "/api/metrics" || pathname.startsWith("/api/metrics/");
}
