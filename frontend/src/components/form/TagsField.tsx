"use client";

import { TagsInput, type TagsInputProps } from "@mantine/core";

import { FieldChrome } from "@/components/form/FieldChrome";
import { FieldMode } from "@/components/form/FieldMode";
import { collectNotes, type FieldChromeProps } from "@/components/form/fieldNotes";

export type TagsFieldProps = Omit<TagsInputProps, "disabled" | "readOnly"> &
  FieldChromeProps & {
    editable: boolean;
  };

export function TagsField({
  editable,
  notes,
  openSignal,
  bare = false,
  ...props
}: TagsFieldProps) {
  const values = props.value ?? [];
  const merged = bare ? [] : collectNotes(props.error, notes);
  return (
    <FieldMode
      editable={editable}
      label={props.label}
      description={bare ? undefined : props.description}
      notes={merged}
      openSignal={openSignal}
      value={values.length === 0 ? undefined : values.join(", ")}
      style={props.style}
      w={props.w}
    >
      <FieldChrome
        label={props.label}
        description={props.description}
        notes={merged}
        required={props.required}
        id={props.id}
        openSignal={openSignal}
        editSignal={props.value}
        bare={bare}
      >
        {({ id, invalid }) => (
          <TagsInput
            {...props}
            id={id}
            label={undefined}
            description={undefined}
            error={invalid || undefined}
            withAsterisk={false}
          />
        )}
      </FieldChrome>
    </FieldMode>
  );
}
