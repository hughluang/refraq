"use client";

import { Group, Switch, type SwitchProps } from "@mantine/core";
import { useTranslate } from "@refinedev/core";

import { FieldMarks } from "@/components/form/FieldChrome";
import { FieldMode } from "@/components/form/FieldMode";
import { collectNotes, presentDescription, type FieldChromeProps } from "@/components/form/fieldNotes";

export type SwitchFieldProps = Omit<SwitchProps, "disabled" | "readOnly"> &
  FieldChromeProps & {
    editable: boolean;
  };

export function SwitchField({
  editable,
  notes,
  openSignal,
  bare = false,
  ...props
}: SwitchFieldProps) {
  const t = useTranslate();
  const text = props.checked ? t("form.value.yes") : t("form.value.no");
  const merged = bare ? [] : collectNotes(props.error, notes);
  const labelText = typeof props.label === "string" ? props.label : undefined;
  return (
    <FieldMode
      editable={editable}
      label={props.label}
      description={bare ? undefined : props.description}
      notes={merged}
      openSignal={openSignal}
      value={text}
      style={props.style}
    >
      {bare || (merged.length === 0 && presentDescription(props.description) == null) ? (
        <Switch {...props} description={undefined} error={undefined} />
      ) : (
        <Group gap={4} align="center" wrap="nowrap" style={props.style}>
          <Switch
            {...props}
            style={undefined}
            description={undefined}
            error={merged.some((note) => note.tone === "error") || undefined}
          />
          <FieldMarks
            label={labelText}
            description={props.description}
            notes={merged}
            openSignal={openSignal}
            editSignal={props.checked}
          />
        </Group>
      )}
    </FieldMode>
  );
}
