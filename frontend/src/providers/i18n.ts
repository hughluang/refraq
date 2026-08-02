"use client";

import i18n from "i18next";
import { initReactI18next } from "react-i18next";

import enUS from "@/locales/en-US/common.json";
import zhCN from "@/locales/zh-CN/common.json";

export const SUPPORTED_LOCALES = ["zh-CN", "en-US"] as const;
export type Locale = (typeof SUPPORTED_LOCALES)[number];

export function getDefaultLocale(): Locale {
  const candidate = process.env.NEXT_PUBLIC_DEFAULT_LOCALE;
  if (candidate === "en-US" || candidate === "zh-CN") {
    return candidate;
  }
  return "zh-CN";
}

const resources = {
  "zh-CN": { translation: zhCN },
  "en-US": { translation: enUS },
};

if (!i18n.isInitialized) {
  void i18n.use(initReactI18next).init({
    resources,
    lng: getDefaultLocale(),
    fallbackLng: "zh-CN",
    interpolation: { escapeValue: false },
    returnNull: false,
  });
}

export { i18n };
