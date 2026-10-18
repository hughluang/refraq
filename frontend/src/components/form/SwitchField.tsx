"use client";

import { Group, Stack, Switch, Text, type SwitchProps } from "@mantine/core";
import { useTranslate } from "@refinedev/core";
import { useId } from "react";

import { FieldMarks } from "@/components/form/FieldChrome";
import { FieldMode } from "@/components/form/FieldMode";
import {
  collectNotes,
  joinDescribedBy,
  presentDescription,
  type FieldChromeProps,
} from "@/components/form/fieldNotes";

export type SwitchFieldProps = Omit<SwitchProps, "disabled" | "readOnly"> &
  FieldChromeProps & {
    editable: boolean;
  };

export function SwitchField({
  editable,
  notes,
  openSignal,
  bare = false,
  helper,
  ...props
}: SwitchFieldProps) {
  const t = useTranslate();
  const helperId = useId();
  const text = props.checked ? t("form.value.yes") : t("form.value.no");
  const merged = bare ? [] : collectNotes(props.error, notes);
  const labelText = typeof props.label === "string" ? props.label : undefined;
  const helperText = bare ? undefined : presentDescription(helper);
  const describedBy = joinDescribedBy(
    props["aria-describedby"],
    helperText != null ? helperId : undefined,
  );
  const control =
    bare || (merged.length === 0 && presentDescription(props.description) == null) ? (
      <Switch {...props} description={undefined} error={undefined} aria-describedby={describedBy} />
    ) : (
      <Group gap={4} align="center" wrap="nowrap" style={props.style}>
        <Switch
          {...props}
          style={undefined}
          description={undefined}
          error={merged.some((note) => note.tone === "error") || undefined}
          aria-describedby={describedBy}
        />
        <FieldMarks
          label={labelText}
          description={props.description}
          notes={merged}
          openSignal={openSignal}
          editSignal={props.checked}
        />
      </Group>
    );
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
      {helperText == null ? (
        control
      ) : (
        <Stack gap={4}>
          {control}
          <Text id={helperId} className="field-chrome__helper" size="xs" c="dimmed" component="div">
            {helperText}
          </Text>
        </Stack>
      )}
    </FieldMode>
  );
}
