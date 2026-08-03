"use client";

import resourcesToBackend from "i18next-resources-to-backend";
import { I18nProvider, type I18nProviderProps } from "next-i18next/client";
import type { ReactNode } from "react";

import { getDefaultLocale, SUPPORTED_LOCALES } from "@/providers/locale-catalog";

const localeBackend = resourcesToBackend(
  (language: string, namespace: string) =>
    import(`../locales/${language}/${namespace}.json`),
);

type AppI18nProviderProps = {
  children: ReactNode;
  language: I18nProviderProps["language"];
  resources?: I18nProviderProps["resources"];
};

/**
 * Client I18nProvider with app locale defaults and a dynamic-import backend
 * matching i18n.config resourceLoader. SSR hydrates the current language via
 * `resources`; other locales load on demand.
 */
export function AppI18nProvider({
  children,
  language,
  resources,
}: AppI18nProviderProps) {
  return (
    <I18nProvider
      language={language}
      resources={resources}
      supportedLngs={[...SUPPORTED_LOCALES]}
      defaultNS="common"
      fallbackLng={getDefaultLocale()}
      use={[localeBackend]}
    >
      {children}
    </I18nProvider>
  );
}
