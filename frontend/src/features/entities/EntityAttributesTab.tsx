"use client";

import { Stack, Text } from "@mantine/core";
import { useTranslate } from "@refinedev/core";

import {
  AttributeEditor,
  type AttributeFormApi,
} from "@/features/entities/AttributeEditor";

type Props = {
  shapeForm: AttributeFormApi;
  canWrite: boolean;
  hintKey?: string;
};

export function EntityAttributesTab({
  shapeForm,
  canWrite,
  hintKey,
}: Props) {
  const t = useTranslate();

  return (
    <Stack gap="sm">
      {hintKey ? (
        <Text size="sm" c="dimmed">
          {t(hintKey)}
        </Text>
      ) : null}
      <AttributeEditor form={shapeForm} disabled={!canWrite} />
    </Stack>
  );
}
