import { Input, Stack, Text } from "@mantine/core";
import type { ReactNode } from "react";

type DisplayFieldProps = {
  label: ReactNode;
  value?: ReactNode;
  description?: ReactNode;
  fallback?: ReactNode;
};

export function DisplayField({
  label,
  value,
  description,
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

  return (
    <Stack gap={2}>
      <Input.Label>{label}</Input.Label>
      {display}
      {description ? (
        <Input.Description>{description}</Input.Description>
      ) : null}
    </Stack>
  );
}
