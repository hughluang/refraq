"use client";

import { Textarea, type TextareaProps } from "@mantine/core";

import { FieldDisplay } from "@/components/form/FieldDisplay";

export type TextareaFieldProps = Omit<TextareaProps, "disabled" | "readOnly"> & {
  editable: boolean;
};

export function TextareaField({ editable, ...props }: TextareaFieldProps) {
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
  return <Textarea {...props} />;
}
