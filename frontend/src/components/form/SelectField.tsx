"use client";

import { Select, type SelectProps } from "@mantine/core";

import { FieldMode } from "@/components/form/FieldMode";
import { optionLabel } from "@/components/form/optionLabel";

export type SelectFieldProps = Omit<SelectProps, "disabled" | "readOnly"> & {
  editable: boolean;
};

export function SelectField({ editable, ...props }: SelectFieldProps) {
  const raw = props.value;
  const text =
    raw == null || raw === "" ? undefined : optionLabel(props.data ?? [], String(raw));
  return (
    <FieldMode
      editable={editable}
      label={props.label}
      description={props.description}
      value={text}
      style={props.style}
      w={props.w}
    >
      <Select {...props} />
    </FieldMode>
  );
}
