export const CONSOLE_MAIN_ID = "console-main";
export const NAV_MODE_KEY = "refraq.console.nav-mode";
export const NAV_EXPANDED_WIDTH = 240;
export const NAV_RAIL_WIDTH = 72;

export function activeNavigationRoute(
  pathname: string,
  routes: readonly string[],
): string | null {
  let best: string | null = null;
  for (const route of routes) {
    if (!route) continue;
    const matches = pathname === route || pathname.startsWith(`${route}/`);
    if (!matches) continue;
    if (best === null || route.length > best.length) best = route;
  }
  return best;
}

export function isEditableShortcutTarget(target: EventTarget | null): boolean {
  if (!(target instanceof HTMLElement)) return false;
  return Boolean(
    target.closest(
      "input, textarea, select, [contenteditable='true'], .cm-editor, .channel-canvas-stage",
    ),
  );
}

export function isChannelCanvasTarget(target: EventTarget | null): boolean {
  if (target instanceof Element && target.closest(".react-flow")) return true;
  const active = document.activeElement;
  return active instanceof Element && Boolean(active.closest(".react-flow"));
}
