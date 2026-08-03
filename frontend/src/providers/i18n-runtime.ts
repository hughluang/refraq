import type { i18n as I18nInstance } from "i18next";

/** Bound from RefineRoot so non-React modules (e.g. authProvider) can translate. */
let clientI18n: I18nInstance | null = null;

export function bindClientI18n(instance: I18nInstance): void {
  clientI18n = instance;
}

export function translateKey(key: string): string {
  if (!clientI18n) {
    return key;
  }
  return String(clientI18n.t(key));
}
