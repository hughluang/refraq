"use client";

import { Box, Text, type BoxProps, type MantineStyleProp } from "@mantine/core";
import type { ReactNode } from "react";

import { DisplayField } from "@/components/display/DisplayField";
import type { FieldNote } from "@/components/form/fieldNotes";

type FieldDisplayProps = {
  label?: ReactNode;
  description?: ReactNode;
  helper?: ReactNode;
  notes?: readonly FieldNote[];
  openSignal?: string | null;
  value?: ReactNode;
  style?: MantineStyleProp;
  w?: BoxProps["w"];
};

export function FieldDisplay({
  label,
  description,
  helper,
  notes = [],
  openSignal = null,
  value,
  style,
  w,
}: FieldDisplayProps) {
  const empty = value == null || value === "";
  if (label == null) {
    return (
      <Text size="sm" style={style}>
        {empty ? "—" : value}
      </Text>
    );
  }
  return (
    <Box style={style} w={w}>
      <DisplayField
        label={label}
        description={description}
        helper={helper}
        notes={notes}
        openSignal={openSignal}
        value={value}
      />
    </Box>
  );
}
