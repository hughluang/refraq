"use client";

import { NumberInput, type NumberInputProps } from "@mantine/core";

import { FieldChrome } from "@/components/form/FieldChrome";
import { FieldMode } from "@/components/form/FieldMode";
import { collectNotes, type FieldChromeProps } from "@/components/form/fieldNotes";

export type NumberFieldProps = Omit<NumberInputProps, "disabled" | "readOnly"> &
  FieldChromeProps & {
    editable: boolean;
  };

function numberText(value: NumberInputProps["value"]): string | number | undefined {
  if (value == null || value === "") return undefined;
  return value;
}

export function NumberField({
  editable,
  notes,
  openSignal,
  bare = false,
  ...props
}: NumberFieldProps) {
  const merged = bare ? [] : collectNotes(props.error, notes);
  return (
    <FieldMode
      editable={editable}
      label={props.label}
      description={bare ? undefined : props.description}
      notes={merged}
      openSignal={openSignal}
      value={numberText(props.value)}
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
          <NumberInput
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
