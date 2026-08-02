import { ColorSchemeScript, mantineHtmlProps } from "@mantine/core";
import type { Metadata } from "next";
import type { ReactNode } from "react";

import { AppProviders } from "@/app/providers";

export const dynamic = "force-dynamic";

export const metadata: Metadata = {
  title: "Refraq",
  description: "Data Product Integration Platform",
};

export default function RootLayout({ children }: { children: ReactNode }) {
  return (
    <html lang="zh-CN" {...mantineHtmlProps}>
      <head>
        <ColorSchemeScript defaultColorScheme="light" />
      </head>
      <body>
        <AppProviders>{children}</AppProviders>
      </body>
    </html>
  );
}
