"use client";

import { Switch, type SwitchProps } from "@mantine/core";
import { useTranslate } from "@refinedev/core";

import { FieldMode } from "@/components/form/FieldMode";

export type SwitchFieldProps = Omit<SwitchProps, "disabled" | "readOnly"> & {
  editable: boolean;
};

export function SwitchField({ editable, ...props }: SwitchFieldProps) {
  const t = useTranslate();
  const text = props.checked ? t("form.value.yes") : t("form.value.no");
  return (
    <FieldMode
      editable={editable}
      label={props.label}
      description={props.description}
      value={text}
      style={props.style}
    >
      <Switch {...props} />
    </FieldMode>
  );
}
