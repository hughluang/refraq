"use client";

import { SegmentedControl, type MantineSize } from "@mantine/core";

import { FieldMode } from "@/components/form/FieldMode";

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
  const match = data.find((item) => item.value === value);
  return (
    <FieldMode editable={editable} value={match?.label}>
      <SegmentedControl
        data={data}
        value={value ?? ""}
        onChange={onChange}
        size={size}
        fullWidth={fullWidth}
        aria-label={ariaLabel}
      />
    </FieldMode>
  );
}
