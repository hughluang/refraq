"use client";

import { Textarea, type TextareaProps } from "@mantine/core";

import { FieldChrome } from "@/components/form/FieldChrome";
import { FieldMode } from "@/components/form/FieldMode";
import { collectNotes, type FieldChromeProps } from "@/components/form/fieldNotes";

export type TextareaFieldProps = Omit<TextareaProps, "disabled" | "readOnly"> &
  FieldChromeProps & {
    editable: boolean;
  };

export function TextareaField({
  editable,
  notes,
  openSignal,
  bare = false,
  ...props
}: TextareaFieldProps) {
  const value = props.value;
  const text = value == null || value === "" ? undefined : String(value);
  const merged = bare ? [] : collectNotes(props.error, notes);
  return (
    <FieldMode
      editable={editable}
      label={props.label}
      description={bare ? undefined : props.description}
      notes={merged}
      openSignal={openSignal}
      value={text}
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
          <Textarea
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
