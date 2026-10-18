"use client";

import { useTranslate } from "@refinedev/core";

import { CONSOLE_MAIN_ID } from "@/components/layout/consoleNav";

export function ConsoleSkipLink() {
  const t = useTranslate();
  return (
    <a className="console-skip-link" href={`#${CONSOLE_MAIN_ID}`}>
      {t("layout.skipToContent")}
    </a>
  );
}
