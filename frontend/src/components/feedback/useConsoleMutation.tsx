"use client";

import { Button } from "@mantine/core";
import { useTranslate } from "@refinedev/core";
import { useRef, useState, type ReactNode } from "react";

import { ConfirmActionModal } from "@/components/feedback/ConfirmActionModal";
import { type ConsoleMutation } from "@/components/feedback/consoleAction";
import { ProblemDetails } from "@/components/feedback/ProblemDetails";
import { saveFailureFrom, type SaveFailure } from "@/components/form/FormErrorSummary";
import { ApiError } from "@/lib/api";
import { problemMessage } from "@/lib/problem";
import {
  dismissConsoleNotification,
  presentConsoleNotification,
} from "@/providers/notification-provider";

const UNDO_MS = 8000;

type PendingConfirm = Extract<ConsoleMutation, { safety: "confirm" }>;
type UndoableMutation = Extract<ConsoleMutation, { safety: "undoable" }>;

type Translate = (key: string, options?: Record<string, unknown>) => string;

export type ConsoleMutationController = {
  run: (operation: ConsoleMutation) => void;
  submitting: boolean;
  activeKey: string | null;
  isSubmitting: (key: string) => boolean;
  failure: SaveFailure | null;
  dialog: ReactNode;
};

function successTitle(t: Translate, outcome: string, recordName: string) {
  return t("feedback.success.title", { outcome, record: recordName });
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

function reportFailure(
  t: Translate,
  operation: ConsoleMutation,
  error: unknown,
  setFailure: (failure: SaveFailure | null) => void,
) {
  if (operation.applyApiError) {
    setFailure(
      saveFailureFrom(t, error, operation.applyApiError(error), t("problems.unknown")),
    );
    return;
  }
  setFailure(null);
  const api = error instanceof ApiError ? error : null;
  const detail = api?.detail?.trim() ? api.detail : null;
  const requestId = api?.requestId?.trim() ? api.requestId : null;
  presentConsoleNotification({
    type: "error",
    title: problemMessage(t, error, t("problems.unknown")),
    message:
      detail || requestId
        ? (
            <ProblemDetails detail={detail} requestId={requestId} labels={detailLabels(t)} />
          )
        : "",
  });
}

function UndoNotice({ label, onUndo }: { label: string; onUndo: () => void }) {
  return (
    <Button type="button" size="compact-xs" variant="subtle" onClick={onUndo}>
      {label}
    </Button>
  );
}

export function useConsoleMutation(): ConsoleMutationController {
  const t = useTranslate() as Translate;
  const inFlight = useRef(false);
  const pendingRef = useRef<PendingConfirm | null>(null);
  const [submitting, setSubmitting] = useState(false);
  const [activeKey, setActiveKey] = useState<string | null>(null);
  const [failure, setFailure] = useState<SaveFailure | null>(null);
  const [confirm, setConfirm] = useState<PendingConfirm | null>(null);

  function release() {
    inFlight.current = false;
    setSubmitting(false);
    setActiveKey(null);
  }

  async function refresh(operation: ConsoleMutation) {
    try {
      await operation.onSuccess?.();
    } catch (error) {
      reportFailure(t, operation, error, setFailure);
    }
  }

  function announceSuccess(operation: ConsoleMutation) {
    const title = successTitle(t, operation.outcome, operation.recordName);
    if (operation.safety !== "undoable") {
      presentConsoleNotification({ type: "success", title });
      return;
    }
    const undoable: UndoableMutation = operation;
    let noticeId = "";
    noticeId = presentConsoleNotification({
      type: "success",
      title,
      autoClose: UNDO_MS,
      message: (
        <UndoNotice
          label={t("feedback.undo")}
          onUndo={() => {
            dismissConsoleNotification(noticeId);
            void performUndo(undoable);
          }}
        />
      ),
    });
  }

  async function perform(operation: ConsoleMutation) {
    if (inFlight.current) return;
    inFlight.current = true;
    setSubmitting(true);
    setActiveKey(operation.key ?? null);
    setFailure(null);
    try {
      await operation.execute();
      pendingRef.current = null;
      setConfirm(null);
      announceSuccess(operation);
    } catch (error) {
      reportFailure(t, operation, error, setFailure);
      return;
    } finally {
      release();
    }
    await refresh(operation);
  }

  async function performUndo(operation: UndoableMutation) {
    if (inFlight.current) return;
    inFlight.current = true;
    setSubmitting(true);
    setActiveKey(operation.key ?? null);
    try {
      await operation.undo();
      presentConsoleNotification({
        type: "success",
        title: successTitle(t, t("feedback.undo.done"), operation.recordName),
      });
    } catch (error) {
      reportFailure(t, operation, error, setFailure);
      return;
    } finally {
      release();
    }
    await refresh(operation);
  }

  function run(operation: ConsoleMutation) {
    if (inFlight.current) return;
    if (operation.safety === "confirm") {
      if (pendingRef.current) return;
      pendingRef.current = operation;
      setConfirm(operation);
      return;
    }
    void perform(operation);
  }

  function dismissConfirm() {
    if (inFlight.current) return;
    pendingRef.current = null;
    setConfirm(null);
  }

  const dialog = confirm ? (
    <ConfirmActionModal
      opened
      onClose={dismissConfirm}
      title={confirm.title ?? t("feedback.confirm.title", { record: confirm.recordName })}
      body={t("feedback.confirm.body", {
        record: confirm.recordName,
        consequence: confirm.consequence,
      })}
      confirmLabel={confirm.confirmLabel}
      confirmColor={confirm.confirmColor}
      loading={submitting}
      onConfirm={() => {
        void perform(confirm);
      }}
    />
  ) : null;

  return {
    run,
    submitting,
    activeKey,
    isSubmitting: (key: string) => submitting && activeKey === key,
    failure,
    dialog,
  };
}
