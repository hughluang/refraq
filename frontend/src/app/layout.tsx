import { mantineHtmlProps } from "@mantine/core";
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

/**
 * Inline blocking color-scheme init matching @mantine/core ColorSchemeScript.
 * ColorSchemeScript is a Client Component that emits <script>; React 19 / Next.js 16
 * warn and do not execute scripts rendered from the client tree. Emitting the same
 * script from this Server Component keeps pre-paint localStorage application.
 */
const MANTINE_COLOR_SCHEME_SCRIPT = `try {
  var _colorScheme = window.localStorage.getItem("mantine-color-scheme-value");
  var colorScheme = _colorScheme === "light" || _colorScheme === "dark" || _colorScheme === "auto" ? _colorScheme : "light";
  var computedColorScheme = colorScheme !== "auto" ? colorScheme : window.matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light";
  document.documentElement.setAttribute("data-mantine-color-scheme", computedColorScheme);
} catch (e) {}
`;

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
        <script
          data-mantine-script
          dangerouslySetInnerHTML={{ __html: MANTINE_COLOR_SCHEME_SCRIPT }}
        />
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
