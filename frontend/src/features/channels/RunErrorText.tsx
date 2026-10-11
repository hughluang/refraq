"use client";

import { Text } from "@mantine/core";
import { useTranslate } from "@refinedev/core";

import { formatRunError } from "@/features/channels/problemLabel";

export function RunErrorText({
  code,
  message,
  empty = "",
}: {
  code: string | null;
  message: string | null;
  empty?: string;
}) {
  const t = useTranslate();
  const error = formatRunError(t, code, message);
  if (!error.label) return empty;
  return (
    <>
      {error.label}
      {error.detail ? (
        <Text span size="xs" c="dimmed" ml={6}>
          {error.detail}
        </Text>
      ) : null}
    </>
  );
}
