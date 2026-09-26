"use client";

import { SegmentedControl, Text, type MantineSize } from "@mantine/core";

export type SegmentOption = {
  value: string;
  label: string;
};

type SegmentedFieldProps = {
  editable: boolean;
  data: SegmentOption[];
  value: string | null;
  onChange?: (value: string) => void;
  size?: MantineSize;
  fullWidth?: boolean;
  "aria-label"?: string;
};

export function SegmentedField({
  editable,
  data,
  value,
  onChange,
  size,
  fullWidth,
  "aria-label": ariaLabel,
}: SegmentedFieldProps) {
  if (!editable) {
    const match = data.find((item) => item.value === value);
    return <Text size="sm">{match?.label}</Text>;
  }

  return (
    <SegmentedControl
      data={data}
      value={value ?? ""}
      onChange={onChange}
      size={size}
      fullWidth={fullWidth}
      aria-label={ariaLabel}
    />
  );
}
