"use client";

import { NumberInput, type NumberInputProps } from "@mantine/core";

import { FieldMode } from "@/components/form/FieldMode";

export type NumberFieldProps = Omit<NumberInputProps, "disabled" | "readOnly"> & {
  editable: boolean;
};

function numberText(value: NumberInputProps["value"]): string | number | undefined {
  if (value == null || value === "") return undefined;
  return value;
}

export function NumberField({ editable, ...props }: NumberFieldProps) {
  return (
    <FieldMode
      editable={editable}
      label={props.label}
      description={props.description}
      value={numberText(props.value)}
      style={props.style}
      w={props.w}
    >
      <NumberInput {...props} />
    </FieldMode>
  );
}
