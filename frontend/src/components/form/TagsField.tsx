"use client";

import { TagsInput, type TagsInputProps } from "@mantine/core";

import { FieldMode } from "@/components/form/FieldMode";

export type TagsFieldProps = Omit<TagsInputProps, "disabled" | "readOnly"> & {
  editable: boolean;
};

export function TagsField({ editable, ...props }: TagsFieldProps) {
  const values = props.value ?? [];
  return (
    <FieldMode
      editable={editable}
      label={props.label}
      description={props.description}
      value={values.length === 0 ? undefined : values.join(", ")}
      style={props.style}
      w={props.w}
    >
      <TagsInput {...props} />
    </FieldMode>
  );
}
