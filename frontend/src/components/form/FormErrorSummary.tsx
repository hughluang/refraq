"use client";

import { Alert, Stack, Text } from "@mantine/core";
import { useTranslate } from "@refinedev/core";

import { ProblemDetails } from "@/components/feedback/ProblemDetails";
import type { ApplyApiErrorResult } from "@/components/form/useConsoleForm";
import { ApiError, type ApiFieldDetail } from "@/lib/api";
import { problemMessage } from "@/lib/problem";

export type SaveFailure = {
  message: string;
  detail: string | null;
  requestId: string | null;
  unmapped: readonly ApiFieldDetail[];
};

type Translate = (key: string) => string;

/**
 * Show the summary when nothing was mapped onto a field, the status is not 422,
 * or some details stayed unmapped. A fully mapped 422 stays on the fields.
 * The main line is the problem presenter, never the server detail.
 */
export function saveFailureFrom(
  t: Translate,
  error: unknown,
  result: ApplyApiErrorResult,
  fallback: string,
): SaveFailure | null {
  const api = error instanceof ApiError ? error : null;
  const show =
    result.unmapped.length > 0 ||
    !api ||
    api.status !== 422 ||
    result.mapped.length === 0;
  if (!show) return null;
  return {
    message: problemMessage(t, error, fallback),
    detail: api?.detail ?? null,
    requestId: api?.requestId ?? null,
    unmapped: result.unmapped,
  };
}

type SummaryView = {
  message: string;
  detail?: string | null;
  requestId?: string | null;
  unmapped?: readonly ApiFieldDetail[];
};

export type FormErrorSummaryProps =
  | SummaryView
  | {
      failure: SaveFailure | null;
    };

function unmappedLine(detail: ApiFieldDetail): string | null {
  const field = detail.field?.trim() ?? "";
  const message = detail.message?.trim() || detail.code?.trim() || "";
  if (field && message) return `${field}: ${message}`;
  return field || message || null;
}

function SummaryAlert({ message, detail, requestId, unmapped }: SummaryView) {
  const t = useTranslate();
  const lines = (unmapped ?? [])
    .map(unmappedLine)
    .filter((line): line is string => line != null);

  return (
    <Alert color="red" variant="light" role="alert">
      <Stack gap="xs">
        <Text size="sm">{message}</Text>
        <ProblemDetails
          detail={detail ?? null}
          requestId={requestId ?? null}
          extraLines={lines}
          labels={{
            summary: t("form.error.details"),
            requestId: t("common.requestId"),
            copy: t("form.error.copy"),
            copied: t("common.copy.success"),
            copyFailed: t("common.copy.failed"),
          }}
        />
      </Stack>
    </Alert>
  );
}

export function FormErrorSummary(props: FormErrorSummaryProps) {
  if ("failure" in props) {
    if (!props.failure) return null;
    return (
      <SummaryAlert
        message={props.failure.message}
        detail={props.failure.detail}
        requestId={props.failure.requestId}
        unmapped={props.failure.unmapped}
      />
    );
  }
  return <SummaryAlert {...props} />;
}
