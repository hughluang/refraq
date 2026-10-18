"use client";

import "@mantine/core/styles.css";
import "@mantine/dates/styles.css";
import "@mantine/notifications/styles.css";
import "@mantine/nprogress/styles.css";

import { MantineProvider } from "@mantine/core";
import { useMemo, type ReactNode } from "react";

import { useBranding } from "@/features/branding/BrandingProvider";
import { ConsoleNotifications } from "@/providers/notification-provider";
import { RefineRoot } from "@/providers/refine";
import { productCssVariablesResolver, productTheme } from "@/theme";

export function AppProviders({ children }: { children: ReactNode }) {
  const { raw } = useBranding();
  const theme = useMemo(
    () => productTheme(raw.primary_shades),
    [raw.primary_shades],
  );

  return (
    <MantineProvider
      theme={theme}
      cssVariablesResolver={productCssVariablesResolver}
      defaultColorScheme="auto"
    >
      <ConsoleNotifications />
      <RefineRoot>{children}</RefineRoot>
    </MantineProvider>
  );
}
