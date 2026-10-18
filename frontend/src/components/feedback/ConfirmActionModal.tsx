"use client";

import { Button, Group, Modal, Stack, Text } from "@mantine/core";
import { useTranslate } from "@refinedev/core";
import { useEffect, useRef, type ReactNode } from "react";

type ConfirmActionModalProps = {
  opened: boolean;
  onClose: () => void;
  title: ReactNode;
  body?: ReactNode;
  children?: ReactNode;
  onConfirm: () => void;
  confirmLabel?: string;
  cancelLabel?: string;
  confirmColor?: string;
  loading?: boolean;
  confirmDisabled?: boolean;
  cancelDisabled?: boolean;
  size?: string;
  stackId?: string;
  centered?: boolean;
};

export function ConfirmActionModal({
  opened,
  onClose,
  title,
  body,
  children,
  onConfirm,
  confirmLabel,
  cancelLabel,
  confirmColor,
  loading = false,
  confirmDisabled = false,
  cancelDisabled,
  size,
  stackId,
  centered = true,
}: ConfirmActionModalProps) {
  const t = useTranslate();
  const cancelRef = useRef<HTMLButtonElement>(null);
  useEffect(() => {
    if (!opened) return;
    const id = window.setTimeout(() => {
      cancelRef.current?.focus();
    }, 0);
    return () => window.clearTimeout(id);
  }, [opened]);
  const bodyNode =
    body == null || body === false ? null : typeof body === "string" ? (
      <Text size="sm">{body}</Text>
    ) : (
      body
    );
  return (
    <Modal
      opened={opened}
      onClose={onClose}
      title={title}
      centered={centered}
      size={size}
      stackId={stackId}
    >
      <Stack gap="md">
        {bodyNode}
        {children}
        <Group justify="flex-end">
          <Button
            ref={cancelRef}
            variant="default"
            data-autofocus
            onClick={onClose}
            disabled={cancelDisabled ?? loading}
          >
            {cancelLabel ?? t("common.cancel")}
          </Button>
          <Button
            color={confirmColor}
            loading={loading}
            disabled={confirmDisabled}
            onClick={onConfirm}
          >
            {confirmLabel ?? t("common.confirm")}
          </Button>
        </Group>
      </Stack>
    </Modal>
  );
}
