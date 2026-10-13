"use client";

import { Textarea, type TextareaProps } from "@mantine/core";

import { FieldMode } from "@/components/form/FieldMode";

export type TextareaFieldProps = Omit<TextareaProps, "disabled" | "readOnly"> & {
  editable: boolean;
};

export function TextareaField({ editable, ...props }: TextareaFieldProps) {
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
      <Textarea {...props} />
    </FieldMode>
  );
}
