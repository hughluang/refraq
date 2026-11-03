import { useModuleIdentityStore } from "@/features/console/module-identity/store";
import { isProtectedPath } from "@/lib/route-scope";
import { loginRedirectAfterSessionExpiry } from "@/lib/return-path";
import { useSessionStore } from "@/providers/session-store";

let redirectStarted = false;
let voluntaryLogout = false;

/** An operator-started logout is in flight. A racing 401 must not look like expiry. */
export function beginVoluntaryLogout(): void {
  voluntaryLogout = true;
}

/** Logout did not succeed. A later dead session can use the expiry redirect again. */
export function cancelVoluntaryLogout(): void {
  voluntaryLogout = false;
}

/** Clear the display summary and hard-navigate once from a protected document. */
export function expireClientSession(): void {
  useSessionStore.getState().clear();
  useModuleIdentityStore.getState().reset();
  if (redirectStarted) return;
  if (typeof window === "undefined") return;
  if (!isProtectedPath(window.location.pathname)) return;
  redirectStarted = true;
  window.location.assign(voluntaryLogout ? "/login" : loginRedirectAfterSessionExpiry());
}
