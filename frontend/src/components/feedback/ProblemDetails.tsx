"use client";

import { Button, Stack, Text } from "@mantine/core";
import { useState } from "react";

import { copyText } from "@/lib/copy-text";

export type ProblemDetailLabels = {
  summary: string;
  requestId: string;
  copy: string;
  copied: string;
  copyFailed: string;
};

export function ProblemDetails({
  detail,
  requestId,
  labels,
  extraLines = [],
}: {
  detail: string | null;
  requestId: string | null;
  labels: ProblemDetailLabels;
  extraLines?: readonly string[];
}) {
  const [copyState, setCopyState] = useState<"idle" | "ok" | "fail">("idle");
  const trimmedDetail = detail?.trim() ?? "";
  const trimmedRequestId = requestId?.trim() ?? "";
  const lines: string[] = [];
  if (trimmedDetail) lines.push(trimmedDetail);
  if (trimmedRequestId) lines.push(`${labels.requestId}: ${trimmedRequestId}`);
  for (const line of extraLines) {
    const trimmed = line.trim();
    if (trimmed) lines.push(trimmed);
  }
  const copyValue = lines.join("\n");
  if (!copyValue) return null;

  async function copyDetails() {
    try {
      await copyText(copyValue);
      setCopyState("ok");
    } catch {
      setCopyState("fail");
    }
  }

  return (
    <details>
      <summary>{labels.summary}</summary>
      <Stack gap={4} mt={4}>
        {trimmedDetail ? (
          <Text size="xs" c="dimmed">
            {trimmedDetail}
          </Text>
        ) : null}
        {trimmedRequestId ? (
          <Text size="xs" c="dimmed">
            {labels.requestId}: {trimmedRequestId}
          </Text>
        ) : null}
        {extraLines.map((line, index) =>
          line.trim() ? (
            <Text key={`${line}-${index}`} size="xs">
              {line}
            </Text>
          ) : null,
        )}
        <Button
          type="button"
          variant="subtle"
          size="compact-xs"
          onClick={() => {
            void copyDetails();
          }}
        >
          {labels.copy}
        </Button>
        {copyState === "ok" ? <Text size="xs">{labels.copied}</Text> : null}
        {copyState === "fail" ? <Text size="xs">{labels.copyFailed}</Text> : null}
      </Stack>
    </details>
  );
}
