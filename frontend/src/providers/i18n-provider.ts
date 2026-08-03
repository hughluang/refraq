import type { I18nProvider } from "@refinedev/core";
import type { i18n as I18nInstance, TFunction } from "i18next";

import { getDefaultLocale, type Locale } from "@/providers/locale-catalog";

export type { Locale };
export { getDefaultLocale };

/** Build Refine i18nProvider from a react-i18next subscription (useTranslation). */
export function createI18nProvider(
  t: TFunction,
  i18n: I18nInstance,
  changeLocale: (locale: string) => void | Promise<void>,
): I18nProvider {
  return {
    translate: (key: string, options?: unknown, defaultMessage?: string) => {
      const result =
        typeof defaultMessage === "string"
          ? t(key, { ...(options as Record<string, unknown>), defaultValue: defaultMessage })
          : t(key, options as Record<string, unknown> | undefined);
      return String(result);
    },
    changeLocale: (locale: string) => changeLocale(locale),
    getLocale: () =>
      (i18n.resolvedLanguage as Locale | undefined) || getDefaultLocale(),
  };
}
