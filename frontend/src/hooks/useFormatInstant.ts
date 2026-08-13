"use client";

import { useCallback } from "react";

import { formatInstant } from "@/lib/datetime";
import { useSessionStore } from "@/providers/session-store";

/** Format Instants with the current User's Display Timezone (null → browser). */
export function useFormatInstant() {
  const displayTimezone = useSessionStore((s) => s.user?.display_timezone ?? null);
  const locale = useSessionStore((s) => s.user?.locale);

  return useCallback(
    (value: string | null | undefined) =>
      formatInstant(value, {
        timeZone: displayTimezone,
        locale: locale || undefined,
      }),
    [displayTimezone, locale],
  );
}
