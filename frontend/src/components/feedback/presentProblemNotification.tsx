"use client";

import { Button, Stack } from "@mantine/core";

import { ProblemDetails } from "@/components/feedback/ProblemDetails";
import { ApiError, type ApiFieldDetail } from "@/lib/api";
import { problemMessage } from "@/lib/problem";
import { presentConsoleNotification } from "@/providers/notification-provider";

type Translate = (key: string) => string;

export type ProblemNotificationOptions = {
  unmapped?: readonly ApiFieldDetail[];
  onRetry?: () => void;
};

/** `field: message`, else the field, else the message, else the code. */
export function unmappedLine(detail: ApiFieldDetail): string | null {
  const field = detail.field?.trim() ?? "";
  const message = detail.message?.trim() || detail.code?.trim() || "";
  if (field && message) return `${field}: ${message}`;
  return field || message || null;
}

function detailLabels(t: Translate) {
  return {
    summary: t("form.error.details"),
    requestId: t("common.requestId"),
    copy: t("form.error.copy"),
    copied: t("common.copy.success"),
    copyFailed: t("common.copy.failed"),
  };
}

/**
 * Error notification for a failure that is not a form summary.
 * The title is the localized Problem Code. Server detail, the request id,
 * and unmapped field lines stay in the disclosure.
 */
export function presentProblemNotification(
  t: Translate,
  error: unknown,
  options?: ProblemNotificationOptions,
) {
  const api = error instanceof ApiError ? error : null;
  const detail = api?.detail?.trim() ? api.detail : null;
  const requestId = api?.requestId?.trim() ? api.requestId : null;
  const extraLines = (options?.unmapped ?? [])
    .map(unmappedLine)
    .filter((line): line is string => line != null);
  const disclosure =
    detail || requestId || extraLines.length > 0 ? (
      <ProblemDetails
        detail={detail}
        requestId={requestId}
        extraLines={extraLines}
        labels={detailLabels(t)}
      />
    ) : null;
  const retry = options?.onRetry ? (
    <Button type="button" size="compact-xs" variant="subtle" onClick={options.onRetry}>
      {t("common.retry")}
    </Button>
  ) : null;
  presentConsoleNotification({
    type: "error",
    title: problemMessage(t, error, t("problems.unknown")),
    message:
      disclosure && retry ? (
        <Stack gap={4}>
          {disclosure}
          {retry}
        </Stack>
      ) : (
        (disclosure ?? retry ?? "")
      ),
  });
}
