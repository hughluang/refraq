"use client";

import { type BoxProps, type MantineStyleProp } from "@mantine/core";
import type { ReactNode } from "react";

import type { FieldNote } from "@/components/form/fieldNotes";
import { FieldDisplay } from "@/components/form/FieldDisplay";

type FieldModeProps = {
  editable: boolean;
  label?: ReactNode;
  description?: ReactNode;
  notes?: readonly FieldNote[];
  openSignal?: string | null;
  value?: ReactNode;
  style?: MantineStyleProp;
  w?: BoxProps["w"];
  children: ReactNode;
};

export function FieldMode({
  editable,
  label,
  description,
  notes,
  openSignal,
  value,
  style,
  w,
  children,
}: FieldModeProps) {
  if (!editable) {
    return (
      <FieldDisplay
        label={label}
        description={description}
        notes={notes}
        openSignal={openSignal}
        value={value}
        style={style}
        w={w}
      />
    );
  }
  return children;
}
