"use client";

import { TextInput, type TextInputProps } from "@mantine/core";

import { FieldDisplay } from "@/components/form/FieldDisplay";

export type TextFieldProps = Omit<TextInputProps, "disabled" | "readOnly"> & {
  editable: boolean;
};

export function TextField({ editable, ...props }: TextFieldProps) {
  if (!editable) {
    const value = props.value;
    const text =
      value == null || value === "" ? undefined : String(value);
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
  return <TextInput {...props} />;
}
