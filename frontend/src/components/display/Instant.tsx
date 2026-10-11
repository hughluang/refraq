"use client";

import { useFormatInstant } from "@/hooks/useFormatInstant";
import type { Instant as InstantValue } from "@/lib/instant";

/** Localized Instant. The only JSX display for an API timestamp. */
export function Instant({ value }: { value: InstantValue | null | undefined }) {
  const formatInstant = useFormatInstant();
  return formatInstant(value);
}
