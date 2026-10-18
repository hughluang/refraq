"use client";

import { Button, Code, Group, Modal, Stack, Text } from "@mantine/core";
import { useNotification, useTranslate } from "@refinedev/core";
import { useEffect, useState } from "react";

import {
  confirmLeave,
  releaseLeaveGuardSuppression,
  useLeaveGuardRegistration,
} from "@/components/navigation/leaveGuard";
import { copyText } from "@/lib/copy-text";

type Props = {
  secret: string | null;
  onClose: () => void;
};

export function SecretRevealDialog({ secret, onClose }: Props) {
  const t = useTranslate();
  const { open } = useNotification();
  const [copied, setCopied] = useState(false);
  useLeaveGuardRegistration(secret != null && !copied);

  useEffect(() => {
    setCopied(false);
  }, [secret]);

  async function requestClose() {
    if (secret == null) return;
    if (!copied) {
      const allowed = await confirmLeave();
      if (!allowed) return;
      releaseLeaveGuardSuppression();
    }
    onClose();
  }

  async function copySecret() {
    if (!secret) return;
    try {
      await copyText(secret);
      setCopied(true);
      open?.({ type: "success", message: t("common.copy.success") });
    } catch {
      open?.({ type: "error", message: t("common.copy.failed") });
    }
  }

  return (
    <Modal
      opened={secret != null}
      onClose={() => void requestClose()}
      title={t("tokens.secret.title")}
      centered
      closeOnClickOutside={false}
      closeOnEscape
    >
      <Stack gap="md">
        <Text size="sm">{t("tokens.secret.warning")}</Text>
        <Code block style={{ wordBreak: "break-all" }}>
          {secret}
        </Code>
        <Group justify="flex-end">
          <Button type="button" variant="light" onClick={() => void copySecret()}>
            {t("tokens.secret.copy")}
          </Button>
          <Button type="button" onClick={() => void requestClose()}>
            {t("tokens.secret.done")}
          </Button>
        </Group>
      </Stack>
    </Modal>
  );
}
