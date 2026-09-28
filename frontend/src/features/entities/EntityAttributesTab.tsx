"use client";

import { Stack, Text } from "@mantine/core";
import type { UseFormReturnType } from "@mantine/form";
import { useTranslate } from "@refinedev/core";

import {
  AttributeEditor,
  type AttributeReveal,
} from "@/features/entities/AttributeEditor";
import type { EntityRecordFormValues } from "@/features/entities/types";

type Props = {
  form: UseFormReturnType<EntityRecordFormValues>;
  canWrite: boolean;
  selfEntityId: string | null;
  hintKey?: string;
  onEditingChange?: (open: boolean) => void;
  reveal?: AttributeReveal | null;
};

export function EntityAttributesTab({
  form,
  canWrite,
  selfEntityId,
  hintKey,
  onEditingChange,
  reveal,
}: Props) {
  const t = useTranslate();

  return (
    <Stack gap="sm">
      {hintKey ? (
        <Text size="sm" c="dimmed">
          {t(hintKey)}
        </Text>
      ) : null}
      <AttributeEditor
        form={form}
        editable={canWrite}
        selfEntityId={selfEntityId}
        onEditingChange={onEditingChange}
        reveal={reveal}
      />
    </Stack>
  );
}
