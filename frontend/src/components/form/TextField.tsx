"use client";

import { TextInput, type TextInputProps } from "@mantine/core";

import { FieldMode } from "@/components/form/FieldMode";

export type TextFieldProps = Omit<TextInputProps, "disabled" | "readOnly"> & {
  editable: boolean;
};

export function TextField({ editable, ...props }: TextFieldProps) {
  const value = props.value;
  const text = value == null || value === "" ? undefined : String(value);
  return (
    <FieldMode
      editable={editable}
      label={props.label}
      description={props.description}
      value={text}
      style={props.style}
      w={props.w}
    >
      <TextInput {...props} />
    </FieldMode>
  );
}
