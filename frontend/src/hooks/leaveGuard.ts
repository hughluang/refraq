export const LEAVE_GUARD_ALLOW = "allow";

export function isLeaveHref(currentHref: string, nextHref: string): boolean {
  const current = new URL(currentHref);
  const next = new URL(nextHref, currentHref);
  if (next.origin !== current.origin) {
    return true;
  }
  return next.pathname !== current.pathname;
}
