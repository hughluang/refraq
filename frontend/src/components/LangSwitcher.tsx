"use client";

import { Button, Group } from "@mantine/core";
import { useGetLocale, useSetLocale } from "@refinedev/core";
import { useEffect } from "react";

import { SUPPORTED_LOCALES, type Locale } from "@/providers/i18n";

const LABELS: Record<Locale, string> = {
  "zh-CN": "Chinese",
  "en-US": "EN",
};

function syncDocumentLang(locale: Locale) {
  if (typeof document !== "undefined") {
    document.documentElement.lang = locale;
  }
}

export function LangSwitcher() {
  const getLocale = useGetLocale();
  const locale = (getLocale() as Locale) || "zh-CN";
  const changeLocale = useSetLocale();

  useEffect(() => {
    syncDocumentLang(locale);
  }, [locale]);

  return (
    <Group gap={4}>
      {SUPPORTED_LOCALES.map((code) => (
        <Button
          key={code}
          size="compact-xs"
          variant={locale === code ? "filled" : "subtle"}
          onClick={() => {
            changeLocale(code);
            syncDocumentLang(code);
          }}
        >
          {LABELS[code]}
        </Button>
      ))}
    </Group>
  );
}
