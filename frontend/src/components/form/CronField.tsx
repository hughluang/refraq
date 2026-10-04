"use client";

import { TextInput } from "@mantine/core";
import { useTranslate } from "@refinedev/core";
import type { CSSProperties, ReactNode } from "react";

import { cronPhrase, type PresetCron } from "@/components/form/cronPhrase";
import { FieldDisplay } from "@/components/form/FieldDisplay";

type CronFieldShared = {
  label?: ReactNode;
  description?: ReactNode;
  error?: ReactNode;
  required?: boolean;
  style?: CSSProperties;
};

type CronFieldProps = CronFieldShared &
  (
    | {
        editable: true;
        value: string;
        onChange?: (value: string) => void;
      }
    | {
        editable: false;
        value: PresetCron;
        /** Schedule Timezone the wall-clock sentence names. */
        zone: string;
      }
  );

export function CronField(props: CronFieldProps) {
  const t = useTranslate();
  if (!props.editable) {
    const { phrase, raw } = cronPhrase(props.value, t, props.zone);
    return (
      <FieldDisplay
        label={props.label}
        description={props.description}
        value={`${phrase} (${raw})`}
        style={props.style}
      />
    );
  }
  return (
    <TextInput
      label={props.label}
      description={props.description}
      required={props.required}
      error={props.error}
      style={props.style}
      value={props.value}
      onChange={(event) => props.onChange?.(event.currentTarget.value)}
    />
  );
}
