"use client";

import { useTranslate } from "@refinedev/core";

import { useFormatInstant } from "@/hooks/useFormatInstant";
import { UnreadableInstantError } from "@/lib/datetime";
import type { Instant as InstantValue } from "@/lib/instant";

/**
 * Localized Instant. The only JSX display for an API timestamp.
 * An unreadable string fails here only: the contract problem and an optional
 * request id render in place, and the rest of the page stays up.
 */
export function Instant({
  value,
  requestId,
}: {
  value: InstantValue | string | null | undefined;
  requestId?: string | null;
}) {
  const formatInstant = useFormatInstant();
  const t = useTranslate();
  try {
    return formatInstant(value);
  } catch (error) {
    if (!(error instanceof UnreadableInstantError)) throw error;
    const id = requestId?.trim() ?? "";
    return (
      <span>
        <span>{t("problems.API_CONTRACT_INVALID")}</span>
        {id ? <span>{` ${t("common.requestId")}: ${id}`}</span> : null}
      </span>
    );
  }
}
