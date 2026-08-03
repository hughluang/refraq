export const LOCALE_CATALOG = [
  { code: "zh-CN", nativeLabel: "中文" },
  { code: "en-US", nativeLabel: "English" },
] as const;

export type Locale = (typeof LOCALE_CATALOG)[number]["code"];

export const SUPPORTED_LOCALES = LOCALE_CATALOG.map((entry) => entry.code) as readonly Locale[];

export const LOCALE_SELECT_DATA = LOCALE_CATALOG.map((entry) => ({
  value: entry.code,
  label: entry.nativeLabel,
}));

/** Cookie used by next-i18next proxy / useChangeLanguage. */
export const LOCALE_COOKIE_NAME = "refraq.locale";

/** Legacy key; only used for one-time migration into the cookie. */
export const LOCALE_STORAGE_KEY = "refraq.locale";

export function isLocale(value: unknown): value is Locale {
  return typeof value === "string" && (SUPPORTED_LOCALES as readonly string[]).includes(value);
}

export function getDefaultLocale(): Locale {
  const candidate = process.env.NEXT_PUBLIC_DEFAULT_LOCALE;
  if (isLocale(candidate)) {
    return candidate;
  }
  return "en-US";
}

export function getLocaleNativeLabel(code: Locale): string {
  const entry = LOCALE_CATALOG.find((item) => item.code === code);
  return entry?.nativeLabel ?? code;
}
