"use client";

import { MultiSelect, type MultiSelectProps } from "@mantine/core";

import { FieldDisplay } from "@/components/form/FieldDisplay";
import { optionLabels } from "@/components/form/optionLabel";

export type MultiSelectFieldProps = Omit<
  MultiSelectProps,
  "disabled" | "readOnly"
> & {
  editable: boolean;
};

export function MultiSelectField({ editable, ...props }: MultiSelectFieldProps) {
  if (!editable) {
    const values = props.value ?? [];
    return (
      <FieldDisplay
        label={props.label}
        description={props.description}
        value={optionLabels(props.data ?? [], values)}
        style={props.style}
        w={props.w}
      />
    );
  }
  return <MultiSelect {...props} />;
}
