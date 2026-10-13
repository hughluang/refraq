"use client";

import { type BoxProps, type MantineStyleProp } from "@mantine/core";
import type { ReactNode } from "react";

import { FieldDisplay } from "@/components/form/FieldDisplay";

type FieldModeProps = {
  editable: boolean;
  label?: ReactNode;
  description?: ReactNode;
  value?: ReactNode;
  style?: MantineStyleProp;
  w?: BoxProps["w"];
  children: ReactNode;
};

export function FieldMode({
  editable,
  label,
  description,
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
        value={value}
        style={style}
        w={w}
      />
    );
  }
  return children;
}
