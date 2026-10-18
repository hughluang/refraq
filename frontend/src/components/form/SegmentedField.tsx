"use client";

import { SegmentedControl, Stack, Text, type MantineSize } from "@mantine/core";
import { useId, type ReactNode } from "react";

import { FieldMode } from "@/components/form/FieldMode";
import { presentDescription } from "@/components/form/fieldNotes";

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
  helper?: ReactNode;
  "aria-label"?: string;
};

export function SegmentedField({
  editable,
  data,
  value,
  onChange,
  size,
  fullWidth,
  helper,
  "aria-label": ariaLabel,
}: SegmentedFieldProps) {
  const helperId = useId();
  const helperText = presentDescription(helper);
  const match = data.find((item) => item.value === value);
  const control = (
    <SegmentedControl
      data={data}
      value={value ?? ""}
      onChange={onChange}
      size={size}
      fullWidth={fullWidth}
      aria-label={ariaLabel}
      aria-describedby={helperText != null ? helperId : undefined}
    />
  );
  return (
    <FieldMode editable={editable} value={match?.label}>
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
