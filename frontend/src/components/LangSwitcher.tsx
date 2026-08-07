"use client";

import { Button, Menu } from "@mantine/core";
import { useGetIdentity, useNotification } from "@refinedev/core";
import { useChangeLanguage, useT } from "next-i18next/client";

import { patchAccountProfile } from "@/features/account/api";
import { ApiError } from "@/lib/api";
import {
  getDefaultLocale,
  getLocaleNativeLabel,
  isLocale,
  LOCALE_CATALOG,
  LOCALE_COOKIE_NAME,
  type Locale,
} from "@/providers/locale-catalog";
import {
  useSessionStore,
  type CurrentUser,
} from "@/providers/session-store";

function LanguageIcon() {
  return (
    <svg
      width="14"
      height="14"
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="1.75"
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden
    >
      <circle cx="12" cy="12" r="9" />
      <path d="M3 12h18" />
      <path d="M12 3a14 14 0 0 1 0 18" />
      <path d="M12 3a14 14 0 0 0 0 18" />
    </svg>
  );
}

export function LangSwitcher() {
  const { i18n, t } = useT("common");
  const changeLanguage = useChangeLanguage(LOCALE_COOKIE_NAME);
  const { open } = useNotification();
  const { data: user } = useGetIdentity<CurrentUser>();
  const setUser = useSessionStore((s) => s.setUser);
  const current = i18n.resolvedLanguage ?? i18n.language;
  const locale: Locale = isLocale(current) ? current : getDefaultLocale();

  async function selectLocale(next: Locale) {
    if (next === locale) {
      return;
    }
    if (user) {
      try {
        const updated = await patchAccountProfile({ locale: next });
        setUser(updated);
      } catch (err) {
        open?.({
          type: "error",
          message: t("layout.language"),
          description:
            err instanceof ApiError
              ? err.detail
              : t("account.profile.error"),
        });
        return;
      }
    }
    await changeLanguage(next);
  }

  return (
    <Menu position="bottom-end" withinPortal>
      <Menu.Target>
        <Button
          variant="subtle"
          size="compact-sm"
          leftSection={<LanguageIcon />}
          aria-label={t("layout.language")}
        >
          {getLocaleNativeLabel(locale)}
        </Button>
      </Menu.Target>
      <Menu.Dropdown>
        {LOCALE_CATALOG.map((entry) => (
          <Menu.Item
            key={entry.code}
            disabled={entry.code === locale}
            onClick={() => {
              void selectLocale(entry.code);
            }}
          >
            {entry.nativeLabel}
          </Menu.Item>
        ))}
      </Menu.Dropdown>
    </Menu>
  );
}
