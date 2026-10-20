"use client";

import { ColorSchemeScript } from "@mantine/core";
import { useSyncExternalStore } from "react";

/**
 * Mount Mantine's ColorSchemeScript only for the server render and the
 * matching hydration render. defaultColorScheme matches AppProviders.
 *
 * React 19 warns when a later client render creates an executable script,
 * and that script never runs. The browser has already applied the attribute
 * from the server HTML by then.
 */
function subscribe() {
  return () => {};
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
  return <ColorSchemeScript defaultColorScheme="auto" />;
}
