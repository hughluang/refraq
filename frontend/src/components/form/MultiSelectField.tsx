"use client";

import { MultiSelect, type MultiSelectProps } from "@mantine/core";

import { FieldMode } from "@/components/form/FieldMode";
import { optionLabels } from "@/components/form/optionLabel";

export type MultiSelectFieldProps = Omit<
  MultiSelectProps,
  "disabled" | "readOnly"
> & {
  editable: boolean;
};

export function MultiSelectField({ editable, ...props }: MultiSelectFieldProps) {
  const values = props.value ?? [];
  return (
    <FieldMode
      editable={editable}
      label={props.label}
      description={props.description}
      value={optionLabels(props.data ?? [], values)}
      style={props.style}
      w={props.w}
    >
      <MultiSelect {...props} />
    </FieldMode>
  );
}
