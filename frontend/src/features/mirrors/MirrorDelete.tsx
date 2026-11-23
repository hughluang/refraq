"use client";

import { Button, Text } from "@mantine/core";
import { useTranslate } from "@refinedev/core";
import { useEffect, useRef, useState } from "react";
import { ConfirmActionModal } from "@/components/feedback/ConfirmActionModal";
import { presentProblemNotification } from "@/components/feedback/presentProblemNotification";
import { presentConsoleNotification } from "@/providers/notification-provider";
import type { PendingOperation } from "./types";

type Props = {
  source: string;
  table: string;
  enabled: boolean;
  pending: boolean;
  disabled: boolean;
  generation?: string | null;
  remove: (signal: AbortSignal) => Promise<PendingOperation | undefined>;
  onResult: (pending: boolean) => void;
};

export function MirrorDelete({ source, table, enabled, pending, disabled, generation, remove, onResult }: Props) {
  const t = useTranslate();
  const [opened, setOpened] = useState(false);
  const [busy, setBusy] = useState(false);
  const flight = useRef<AbortController | null>(null);
  useEffect(() => () => flight.current?.abort(), []);

  async function confirm() {
    if (enabled || disabled || flight.current) return;
    const controller = new AbortController();
    flight.current = controller;
    setBusy(true);
    try {
      const result = await remove(controller.signal);
      if (controller.signal.aborted) return;
      setOpened(false);
      presentConsoleNotification({ type: "success", title: t(result ? "mirrors.deletePending" : "mirrors.deleted", { table }) });
      onResult(Boolean(result));
    } catch (error) {
      if (!controller.signal.aborted) presentProblemNotification(t, error);
    } finally {
      if (!controller.signal.aborted) setBusy(false);
      flight.current = null;
    }
  }

  return <>
    <Button color="red" variant="light" size="sm" disabled={disabled || busy}
      onClick={() => setOpened(true)}>{t(pending ? "mirrors.continueDelete" : "mirrors.delete")}</Button>
    <ConfirmActionModal opened={opened} title={t("mirrors.delete")} onClose={() => { if (!busy) setOpened(false); }}
      body={t(enabled ? "mirrors.stopBeforeDelete" : "mirrors.deleteImpact", { source, table })}
      confirmLabel={t("mirrors.delete")} confirmColor="red" confirmDisabled={enabled || disabled}
      loading={busy} onConfirm={() => void confirm()}>
      {generation && <Text size="sm">{t("mirrors.generation")} · <code>{generation}</code></Text>}
    </ConfirmActionModal>
  </>;
}
