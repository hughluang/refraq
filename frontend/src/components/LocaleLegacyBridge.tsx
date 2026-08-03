"use client";

import { useChangeLanguage } from "next-i18next/client";
import { useEffect, useRef } from "react";

import {
  isLocale,
  LOCALE_COOKIE_NAME,
  LOCALE_STORAGE_KEY,
} from "@/providers/locale-catalog";

function hasLocaleCookie(): boolean {
  return document.cookie
    .split(";")
    .some((part) => part.trim().startsWith(`${LOCALE_COOKIE_NAME}=`));
}

/**
 * One-time migration: copy legacy localStorage preference into the cookie,
 * then clear localStorage. Cookie remains the only negotiation source.
 */
export function LocaleLegacyBridge() {
  const changeLanguage = useChangeLanguage(LOCALE_COOKIE_NAME);
  const ran = useRef(false);

  useEffect(() => {
    if (ran.current) {
      return;
    }
    ran.current = true;

    try {
      const stored = localStorage.getItem(LOCALE_STORAGE_KEY);
      if (!stored) {
        return;
      }

      if (!hasLocaleCookie() && isLocale(stored)) {
        void changeLanguage(stored).finally(() => {
          localStorage.removeItem(LOCALE_STORAGE_KEY);
        });
        return;
      }

      localStorage.removeItem(LOCALE_STORAGE_KEY);
    } catch {
      // ignore storage access failures
    }
  }, [changeLanguage]);

  return null;
}
