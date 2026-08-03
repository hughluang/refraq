import { ColorSchemeScript, mantineHtmlProps } from "@mantine/core";
import type { Metadata } from "next";
import {
  getResources,
  getT,
  initServerI18next,
} from "next-i18next/server";
import type { ReactNode } from "react";

import { AppProviders } from "@/app/providers";
import { LocaleLegacyBridge } from "@/components/LocaleLegacyBridge";
import { AppI18nProvider } from "@/providers/app-i18n-provider";
import i18nConfig from "../../i18n.config";

initServerI18next(i18nConfig);

export const dynamic = "force-dynamic";

export const metadata: Metadata = {
  title: "Refraq",
  description: "Data Product Integration Platform",
};

export default async function RootLayout({ children }: { children: ReactNode }) {
  const { i18n, lng } = await getT();
  const resources = getResources(i18n);

  return (
    <html lang={lng} {...mantineHtmlProps}>
      <head>
        <ColorSchemeScript defaultColorScheme="light" />
      </head>
      <body>
        <AppI18nProvider language={lng} resources={resources}>
          <LocaleLegacyBridge />
          <AppProviders>{children}</AppProviders>
        </AppI18nProvider>
      </body>
    </html>
  );
}
