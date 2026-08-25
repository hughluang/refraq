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
import { BrandingProvider } from "@/features/branding/BrandingProvider";
import { browserAssetUrl, resolveBranding } from "@/features/branding/resolve";
import { getServerBranding } from "@/features/branding/server";
import { AppI18nProvider } from "@/providers/app-i18n-provider";
import {
  getDefaultLocale,
  isLocale,
  SUPPORTED_LOCALES,
} from "@/providers/locale-catalog";
import i18nConfig from "../../i18n.config";

initServerI18next(i18nConfig);

export const dynamic = "force-dynamic";

export async function generateMetadata(): Promise<Metadata> {
  const [{ t, lng }, branding] = await Promise.all([
    getT(),
    getServerBranding(),
  ]);
  const locale = isLocale(lng) ? lng : getDefaultLocale();
  const resolved = resolveBranding(
    branding,
    locale,
    t("app.description"),
    getDefaultLocale(),
    SUPPORTED_LOCALES,
  );
  const favicon = browserAssetUrl(branding.favicon_url);
  return {
    title: resolved.brandName,
    description: resolved.tagline,
    ...(favicon ? { icons: { icon: favicon } } : {}),
  };
}

export default async function RootLayout({ children }: { children: ReactNode }) {
  const [{ i18n, lng }, branding] = await Promise.all([
    getT(),
    getServerBranding(),
  ]);
  const resources = getResources(i18n);

  return (
    <html lang={lng} {...mantineHtmlProps}>
      <head>
        <ColorSchemeScript defaultColorScheme="light" />
      </head>
      <body>
        <AppI18nProvider language={lng} resources={resources}>
          <BrandingProvider branding={branding}>
            <LocaleLegacyBridge />
            <AppProviders>{children}</AppProviders>
          </BrandingProvider>
        </AppI18nProvider>
      </body>
    </html>
  );
}
