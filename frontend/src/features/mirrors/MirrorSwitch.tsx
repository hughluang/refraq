"use client";

import { Switch } from "@mantine/core";
import { useTranslate } from "@refinedev/core";
import { useState } from "react";
import { ConfirmActionModal } from "@/components/feedback/ConfirmActionModal";

type Props = {
  enabled: boolean;
  disabled: boolean;
  table: string;
  onChange: (enabled: boolean) => void;
};

export function MirrorSwitch({ enabled, disabled, table, onChange }: Props) {
  const t = useTranslate();
  const [confirmOff, setConfirmOff] = useState(false);
  return <>
    <Switch
      role="switch"
      label={t("mirrors.synchronization")}
      checked={enabled}
      disabled={disabled}
      onChange={event => {
        if (event.currentTarget.checked) onChange(true);
        else setConfirmOff(true);
      }}
    />
    <ConfirmActionModal
      opened={confirmOff && enabled && !disabled}
      title={t("mirrors.disable")}
      body={t("mirrors.impact.disable", { table })}
      onClose={() => setConfirmOff(false)}
      onConfirm={() => {
        setConfirmOff(false);
        if (enabled && !disabled) onChange(false);
      }}
    />
  </>;
}
