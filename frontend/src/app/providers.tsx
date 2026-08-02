"use client";

import "@mantine/core/styles.css";
import "@mantine/notifications/styles.css";
import "@/providers/i18n";

import { MantineProvider, createTheme } from "@mantine/core";
import { Notifications } from "@mantine/notifications";
import type { ReactNode } from "react";

import { RefineRoot } from "@/providers/refine";

const theme = createTheme({
  primaryColor: "blue",
});

export function AppProviders({ children }: { children: ReactNode }) {
  return (
    <MantineProvider theme={theme} defaultColorScheme="light">
      <Notifications position="top-right" />
      <RefineRoot>{children}</RefineRoot>
    </MantineProvider>
  );
}
