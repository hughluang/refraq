"use client";

import { useCallback, useMemo } from "react";

import { displayZoneId, formatInstant } from "@/lib/datetime";
import { useSessionStore } from "@/providers/session-store";
import { useTimeZones } from "@/providers/time-zones";

/** Display Timezone id for labels. Null when unset and the browser zone cannot be read. */
export function useDisplayZoneId(): string | null {
  const displayTimezone = useSessionStore(
    (s) => s.user?.display_timezone ?? null,
  );
  return displayZoneId(displayTimezone);
}

/** Format Instants with the current User's Display Timezone (null → browser). */
export function useFormatInstant() {
  const displayTimezone = useSessionStore((s) => s.user?.display_timezone ?? null);
  const locale = useSessionStore((s) => s.user?.locale);
  const { items } = useTimeZones();
  const aliases = useMemo(
    () => items.find((item) => item.id === displayTimezone)?.aliases ?? [],
    [displayTimezone, items],
  );

  return useCallback(
    (value: string | null | undefined) =>
      formatInstant(value, {
        timeZone: displayTimezone,
        aliases,
        locale: locale || undefined,
      }),
    [aliases, displayTimezone, locale],
  );
}
