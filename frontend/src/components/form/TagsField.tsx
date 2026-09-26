"use client";

import { TagsInput, type TagsInputProps } from "@mantine/core";

import { FieldDisplay } from "@/components/form/FieldDisplay";

export type TagsFieldProps = Omit<TagsInputProps, "disabled" | "readOnly"> & {
  editable: boolean;
};

export function TagsField({ editable, ...props }: TagsFieldProps) {
  if (!editable) {
    const values = props.value ?? [];
    return (
      <FieldDisplay
        label={props.label}
        description={props.description}
        value={values.length === 0 ? undefined : values.join(", ")}
        style={props.style}
        w={props.w}
      />
    );
  }
  return <TagsInput {...props} />;
}
