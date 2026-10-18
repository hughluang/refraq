"use client";

import { Button, Menu } from "@mantine/core";
import { useT } from "next-i18next/client";

import { useAccountLocale } from "@/components/accountLocale";
import { LanguageIcon } from "@/components/icons";
import {
  getLocaleNativeLabel,
  LOCALE_CATALOG,
} from "@/providers/locale-catalog";

export function LangSwitcher() {
  const { t } = useT("common");
  const { locale, selectLocale } = useAccountLocale();

  return (
    <Menu position="bottom-end" withinPortal>
      <Menu.Target>
        <Button
          variant="subtle"
          size="compact-sm"
          leftSection={<LanguageIcon size={14} />}
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
