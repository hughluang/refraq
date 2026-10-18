"use client";

import { useGetIdentity, useNotification } from "@refinedev/core";
import { useChangeLanguage, useT } from "next-i18next/client";

import { patchAccountProfile } from "@/features/account/api";
import { problemMessage } from "@/lib/problem";
import {
  getDefaultLocale,
  isLocale,
  LOCALE_CATALOG,
  LOCALE_COOKIE_NAME,
  type Locale,
} from "@/providers/locale-catalog";
import {
  useSessionStore,
  type CurrentUser,
} from "@/providers/session-store";

export function useAccountLocale() {
  const { i18n, t } = useT("common");
  const changeLanguage = useChangeLanguage(LOCALE_COOKIE_NAME);
  const { open } = useNotification();
  const { data: user } = useGetIdentity<CurrentUser>();
  const setUser = useSessionStore((state) => state.setUser);
  const current = i18n.resolvedLanguage ?? i18n.language;
  const locale: Locale = isLocale(current) ? current : getDefaultLocale();
  const other = LOCALE_CATALOG[locale === LOCALE_CATALOG[0].code ? 1 : 0];

  async function selectLocale(next: Locale) {
    if (next === locale) return;
    if (user) {
      try {
        const updated = await patchAccountProfile({ locale: next });
        setUser(updated);
      } catch (error) {
        open?.({
          type: "error",
          message: t("layout.language"),
          description: problemMessage(t, error, t("account.profile.error")),
        });
        return;
      }
    }
    await changeLanguage(next);
  }

  return {
    locale,
    otherLocale: other.code,
    otherLabel: other.nativeLabel,
    selectLocale,
  };
}
