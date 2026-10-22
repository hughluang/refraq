"use client";

import { ProblemDetails } from "@/components/feedback/ProblemDetails";
import { ApiError } from "@/lib/api";
import { problemMessage } from "@/lib/problem";
import { presentConsoleNotification } from "@/providers/notification-provider";

type Translate = (key: string) => string;

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
 * The title is the localized Problem Code. Server detail and the request id
 * stay in the disclosure.
 */
export function presentProblemNotification(t: Translate, error: unknown) {
  const api = error instanceof ApiError ? error : null;
  const detail = api?.detail?.trim() ? api.detail : null;
  const requestId = api?.requestId?.trim() ? api.requestId : null;
  presentConsoleNotification({
    type: "error",
    title: problemMessage(t, error, t("problems.unknown")),
    message:
      detail || requestId ? (
        <ProblemDetails detail={detail} requestId={requestId} labels={detailLabels(t)} />
      ) : (
        ""
      ),
  });
}
