"use client";

import type { I18nProvider } from "@refinedev/core";
import type { i18n as I18nInstance, TFunction } from "i18next";

import { getDefaultLocale, type Locale } from "@/providers/i18n";

export type { Locale };
export { getDefaultLocale };

/** Build Refine i18nProvider from a react-i18next subscription (useTranslation). */
export function createI18nProvider(t: TFunction, i18n: I18nInstance): I18nProvider {
  return {
    translate: (key: string, options?: unknown, defaultMessage?: string) => {
      const result =
        typeof defaultMessage === "string"
          ? t(key, { ...(options as Record<string, unknown>), defaultValue: defaultMessage })
          : t(key, options as Record<string, unknown> | undefined);
      return String(result);
    },
    changeLocale: async (locale: string) => {
      await i18n.changeLanguage(locale);
      if (typeof document !== "undefined") {
        document.documentElement.lang = locale;
      }
    },
    getLocale: () => (i18n.language as Locale) || getDefaultLocale(),
  };
}
