"use client";

import "@mantine/core/styles.css";
import "@mantine/notifications/styles.css";

import { MantineProvider } from "@mantine/core";
import { Notifications } from "@mantine/notifications";
import { useMemo, type ReactNode } from "react";

import { useBranding } from "@/features/branding/BrandingProvider";
import { appTheme } from "@/features/branding/theme";
import { RefineRoot } from "@/providers/refine";

export function AppProviders({ children }: { children: ReactNode }) {
  const { raw } = useBranding();
  const theme = useMemo(
    () => appTheme(raw.primary_shades),
    [raw.primary_shades],
  );

  return (
    <MantineProvider theme={theme} defaultColorScheme="light">
      <Notifications position="top-right" />
      <RefineRoot>{children}</RefineRoot>
    </MantineProvider>
  );
}
