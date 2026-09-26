"use client";

import { Switch, type SwitchProps } from "@mantine/core";
import { useTranslate } from "@refinedev/core";

import { FieldDisplay } from "@/components/form/FieldDisplay";

export type SwitchFieldProps = Omit<SwitchProps, "disabled" | "readOnly"> & {
  editable: boolean;
};

export function SwitchField({ editable, ...props }: SwitchFieldProps) {
  const t = useTranslate();
  if (!editable) {
    const text = props.checked ? t("form.value.yes") : t("form.value.no");
    return (
      <FieldDisplay
        label={props.label}
        description={props.description}
        value={text}
        style={props.style}
      />
    );
  }
  return <Switch {...props} />;
}
