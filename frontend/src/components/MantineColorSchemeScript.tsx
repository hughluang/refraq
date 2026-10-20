"use client";

import { ColorSchemeScript } from "@mantine/core";
import { useSyncExternalStore } from "react";

/**
 * Stored preference on `<html>`. Separate from the resolved
 * `data-mantine-color-scheme`, which is only `light` or `dark`.
 */
export const COLOR_SCHEME_PREFERENCE_ATTRIBUTE = "data-color-scheme-preference";

const LOCAL_STORAGE_KEY = "mantine-color-scheme-value";
const DEFAULT_COLOR_SCHEME = "auto";

/**
 * Mount Mantine's ColorSchemeScript, plus the preference attribute it does
 * not write, only for the server render and the matching hydration render.
 * defaultColorScheme matches AppProviders.
 *
 * React 19 warns when a later client render creates an executable script,
 * and that script never runs. The browser has already applied the attributes
 * from the server HTML by then.
 */
function subscribe() {
  return () => {};
}

function preferenceScript(): string {
  return `try {
  var stored = window.localStorage.getItem("${LOCAL_STORAGE_KEY}");
  var preference = stored === "light" || stored === "dark" || stored === "auto" ? stored : "${DEFAULT_COLOR_SCHEME}";
  document.documentElement.setAttribute("${COLOR_SCHEME_PREFERENCE_ATTRIBUTE}", preference);
} catch (e) {}`;
}

export function MantineColorSchemeScript() {
  const isServerRender = useSyncExternalStore(
    subscribe,
    () => false,
    () => true,
  );
  if (!isServerRender) {
    return null;
  }
  return (
    <>
      <ColorSchemeScript defaultColorScheme="auto" />
      <script dangerouslySetInnerHTML={{ __html: preferenceScript() }} />
    </>
  );
}
