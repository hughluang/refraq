"use client";

import { useTranslate } from "@refinedev/core";
import { useCallback, useMemo } from "react";

import {
  displayZoneId,
  formatInstant,
  resolveDisplayZone,
  showContractInstant,
} from "@/lib/datetime";
import type { Instant } from "@/lib/instant";
import { useSessionStore } from "@/providers/session-store";
import { useTimeZones } from "@/providers/time-zones";

function useDisplayTimeZone() {
  const displayTimezone = useSessionStore(
    (s) => s.user?.display_timezone ?? null,
  );
  const locale = useSessionStore((s) => s.user?.locale);
  const { items } = useTimeZones();
  const aliases = useMemo(
    () => items.find((item) => item.id === displayTimezone)?.aliases ?? [],
    [displayTimezone, items],
  );
  return { displayTimezone, locale, aliases };
}

/** Display Timezone id for labels. Null when unset and the browser zone cannot be read. */
export function useDisplayZoneId(): string | null {
  const { displayTimezone } = useDisplayTimeZone();
  return displayZoneId(displayTimezone);
}

/** Zone that both formats Instants and interprets a typed wall time. */
export function useEntryZone(): string {
  const { displayTimezone, aliases } = useDisplayTimeZone();
  return resolveDisplayZone(displayTimezone, aliases);
}

/** Format an Instant or received Instant text with the User's Display Timezone (null → browser). */
export function useFormatInstant() {
  const { displayTimezone, locale, aliases } = useDisplayTimeZone();

  return useCallback(
    (value: Instant | string | null | undefined) =>
      formatInstant(value, {
        timeZone: displayTimezone,
        aliases,
        locale: locale || undefined,
      }),
    [aliases, displayTimezone, locale],
  );
}

/** Received Instant text for a display cell. An unreadable string stays in that cell. */
export function useShowInstant() {
  const t = useTranslate();
  const formatInstant = useFormatInstant();
  return useCallback(
    (value: string | null | undefined) => showContractInstant(value, formatInstant, t),
    [formatInstant, t],
  );
}
