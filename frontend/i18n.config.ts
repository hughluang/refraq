import type { I18nConfig } from "next-i18next/proxy";

import {
  getDefaultLocale,
  LOCALE_COOKIE_NAME,
  SUPPORTED_LOCALES,
} from "./src/providers/locale-catalog";

const i18nConfig: I18nConfig = {
  supportedLngs: [...SUPPORTED_LOCALES],
  fallbackLng: getDefaultLocale(),
  defaultNS: "common",
  ns: ["common"],
  localeInPath: false,
  cookieName: LOCALE_COOKIE_NAME,
  resourceLoader: (language, namespace) =>
    import(`./src/locales/${language}/${namespace}.json`),
  reloadOnPrerender: process.env.NODE_ENV === "development",
};

export default i18nConfig;
