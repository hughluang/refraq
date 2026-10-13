"use client";

import { TextInput, type TextInputProps } from "@mantine/core";

import { FieldChrome } from "@/components/form/FieldChrome";
import { FieldMode } from "@/components/form/FieldMode";
import { collectNotes, type FieldChromeProps } from "@/components/form/fieldNotes";

export type TextFieldProps = Omit<TextInputProps, "disabled" | "readOnly"> &
  FieldChromeProps & {
    editable: boolean;
  };

export function TextField({
  editable,
  notes,
  openSignal,
  bare = false,
  ...props
}: TextFieldProps) {
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
          <TextInput
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
