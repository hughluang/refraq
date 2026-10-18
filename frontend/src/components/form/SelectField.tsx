"use client";

import { Select, type SelectProps } from "@mantine/core";

import { FieldChrome } from "@/components/form/FieldChrome";
import { FieldMode } from "@/components/form/FieldMode";
import { collectNotes, joinDescribedBy, type FieldChromeProps } from "@/components/form/fieldNotes";
import { optionLabel } from "@/components/form/optionLabel";

export type SelectFieldProps = Omit<SelectProps, "disabled" | "readOnly"> &
  FieldChromeProps & {
    editable: boolean;
  };

export function SelectField({
  editable,
  notes,
  openSignal,
  bare = false,
  helper,
  ...props
}: SelectFieldProps) {
  const raw = props.value;
  const text =
    raw == null || raw === "" ? undefined : optionLabel(props.data ?? [], String(raw));
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
        helper={helper}
        openSignal={openSignal}
        editSignal={props.value}
        bare={bare}
      >
        {({ id, invalid, describedBy }) => (
          <Select
            {...props}
            id={id}
            label={undefined}
            description={undefined}
            error={invalid || undefined}
            withAsterisk={false}
            aria-describedby={joinDescribedBy(props["aria-describedby"], describedBy)}
          />
        )}
      </FieldChrome>
    </FieldMode>
  );
}
