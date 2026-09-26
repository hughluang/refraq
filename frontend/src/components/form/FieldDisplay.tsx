"use client";

import { Box, Text, type BoxProps, type MantineStyleProp } from "@mantine/core";
import type { ReactNode } from "react";

import { DisplayField } from "@/components/display/DisplayField";

type FieldDisplayProps = {
  label?: ReactNode;
  description?: ReactNode;
  value?: ReactNode;
  style?: MantineStyleProp;
  w?: BoxProps["w"];
};

export function FieldDisplay({
  label,
  description,
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
      <DisplayField label={label} description={description} value={value} />
    </Box>
  );
}
