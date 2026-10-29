"use client";

import { Text } from "@mantine/core";
import { useTranslate } from "@refinedev/core";

import { formatRunError } from "@/features/channels/problemLabel";

export function RunErrorText({
  code,
  message,
  empty = "",
  sentence,
}: {
  code: string | null;
  message: string | null;
  empty?: string;
  /** Main line when this surface already names the failure. The occurrence stays the next sentence. */
  sentence?: string;
}) {
  const t = useTranslate();
  const formatted = formatRunError(t, code, message);
  const label = sentence ?? formatted.label;
  if (!label) return empty;
  const detail = formatted.detail && formatted.detail !== label ? formatted.detail : null;
  return (
    <Text size="xs" c="red" component="div" style={{ whiteSpace: "pre-line" }}>
      <span>{label}</span>
      {detail ? (
        <Text span size="xs" c="dimmed">
          {"\n"}
          {detail}
        </Text>
      ) : null}
    </Text>
  );
}
