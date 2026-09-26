"use client";

import { Select, type SelectProps } from "@mantine/core";

import { FieldDisplay } from "@/components/form/FieldDisplay";
import { optionLabel } from "@/components/form/optionLabel";

export type SelectFieldProps = Omit<SelectProps, "disabled" | "readOnly"> & {
  editable: boolean;
};

export function SelectField({ editable, ...props }: SelectFieldProps) {
  if (!editable) {
    const raw = props.value;
    const text =
      raw == null || raw === ""
        ? undefined
        : optionLabel(props.data ?? [], String(raw));
    return (
      <FieldDisplay
        label={props.label}
        description={props.description}
        value={text}
        style={props.style}
        w={props.w}
      />
    );
  }
  return <Select {...props} />;
}
