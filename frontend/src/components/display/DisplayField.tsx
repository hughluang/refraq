import { Input, Stack, Text } from "@mantine/core";
import type { ReactNode } from "react";

import { FieldMarks } from "@/components/form/FieldChrome";
import type { FieldNote } from "@/components/form/fieldNotes";

type DisplayFieldProps = {
  label: ReactNode;
  value?: ReactNode;
  description?: ReactNode;
  notes?: readonly FieldNote[];
  openSignal?: string | null;
  fallback?: ReactNode;
};

export function DisplayField({
  label,
  value,
  description,
  notes = [],
  openSignal = null,
  fallback = "—",
}: DisplayFieldProps) {
  const empty =
    value === null ||
    value === undefined ||
    value === "";
  const display = empty ? (
    <Text c="dimmed" size="sm">
      {fallback}
    </Text>
  ) : typeof value === "string" || typeof value === "number" ? (
    <Text size="sm">{value}</Text>
  ) : (
    value
  );

  const labelText = typeof label === "string" ? label : undefined;
  return (
    <Stack gap={2}>
      <div className="field-chrome__label">
        <Input.Label>{label}</Input.Label>
        <FieldMarks
          label={labelText}
          description={description}
          notes={notes}
          openSignal={openSignal}
          editSignal={value}
        />
      </div>
      {display}
    </Stack>
  );
}
