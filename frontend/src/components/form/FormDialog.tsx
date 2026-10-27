"use client";

import { Button, Group, Modal, type ModalProps } from "@mantine/core";
import { useTranslate } from "@refinedev/core";
import { type FormEvent, type KeyboardEvent, type ReactNode } from "react";

import {
  confirmLeave,
  releaseLeaveGuardSuppression,
  useLeaveGuardRegistration,
} from "@/components/navigation/leaveGuard";

export type FormDialogProps = {
  opened: boolean;
  onClose: () => void;
  title: ReactNode;
  children: ReactNode;
  /** Form-level error summary, rendered above the fields. */
  summary?: ReactNode;
  dirty?: boolean;
  submitting?: boolean;
  /** Already translated. Create and Save stay distinct. */
  submitLabel: string;
  onSubmit: () => void;
  /** Footer control on the left, such as Test. It does not submit the form. */
  leading?: ReactNode;
  size?: ModalProps["size"];
  /** Primary stays visible but does not submit. */
  submitDisabled?: boolean;
  /** Keep fields mounted while the dialog is closed. */
  keepMounted?: boolean;
};

const FIRST_FIELD =
  "input:not([type='hidden']):not([disabled]), textarea:not([disabled]), select:not([disabled])";

function markInitialFocus(node: HTMLFormElement | null) {
  if (!node || node.querySelector("[data-autofocus]")) return;
  node.querySelector<HTMLElement>(FIRST_FIELD)?.setAttribute("data-autofocus", "");
}

export function FormDialog({
  opened,
  onClose,
  title,
  children,
  summary,
  dirty = false,
  submitting = false,
  submitLabel,
  onSubmit,
  leading,
  size,
  submitDisabled = false,
  keepMounted = false,
}: FormDialogProps) {
  const t = useTranslate();
  useLeaveGuardRegistration(Boolean(opened && dirty));

  function requestClose() {
    if (!dirty) {
      onClose();
      return;
    }
    void confirmLeave().then((allowed) => {
      if (!allowed) return;
      // confirmLeave arms a one-shot navigation pass. Closing a dialog is not that navigation.
      releaseLeaveGuardSuppression();
      onClose();
    });
  }

  function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (submitting) return;
    onSubmit();
  }

  function handleKeyDown(event: KeyboardEvent<HTMLFormElement>) {
    if (event.key !== "Enter" || event.nativeEvent.isComposing || event.defaultPrevented) return;
    const target = event.target;
    if (!(target instanceof HTMLElement)) return;
    if (target.tagName === "TEXTAREA" || target.tagName === "BUTTON" || target.isContentEditable) {
      return;
    }
    event.preventDefault();
    event.currentTarget.requestSubmit();
  }

  return (
    <Modal
      opened={opened}
      onClose={requestClose}
      title={title}
      size={size}
      keepMounted={keepMounted}
      closeOnClickOutside={!dirty}
      closeOnEscape
      closeButtonProps={{ "aria-label": t("form.dialog.close") }}
      overlayProps={{ className: "form-dialog-overlay" }}
    >
      <form
        ref={markInitialFocus}
        noValidate
        onSubmit={handleSubmit}
        onKeyDown={handleKeyDown}
      >
        {summary}
        {children}
        <Group
          justify={leading ? "space-between" : "flex-end"}
          mt="md"
          gap="sm"
          wrap="nowrap"
        >
          {leading}
          <Group gap="sm" wrap="nowrap">
            <Button type="button" variant="default" onClick={requestClose}>
              {t("common.cancel")}
            </Button>
            <Button type="submit" loading={submitting} disabled={submitDisabled}>
              {submitLabel}
            </Button>
          </Group>
        </Group>
      </form>
    </Modal>
  );
}
