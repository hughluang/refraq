"use client";

import { Stack, Text } from "@mantine/core";
import { useTranslate } from "@refinedev/core";

import { SwitchField } from "@/components/form/SwitchField";

export type KeepingValues = {
  keepSucceededRuns: boolean;
  keepFailedRuns: boolean;
  keepTestRuns: boolean;
};

export function RunKeepingFields({
  keepSucceededRuns,
  keepFailedRuns,
  keepTestRuns,
  inboundTrigger,
  editable,
  onChange,
}: KeepingValues & {
  inboundTrigger: boolean;
  editable: boolean;
  onChange?: (patch: Partial<KeepingValues>) => void;
}) {
  const t = useTranslate();
  return (
    <Stack gap="sm">
      <SwitchField
        editable={editable}
        label={t("channels.settings.keepSucceededRuns")}
        description={t("channels.settings.keepSucceededRunsHint")}
        checked={keepSucceededRuns}
        onChange={(event) => onChange?.({ keepSucceededRuns: event.currentTarget.checked })}
      />
      {!keepSucceededRuns && inboundTrigger ? (
        <Text size="sm">{t("channels.settings.inboundKeepingBoundary")}</Text>
      ) : null}
      <SwitchField
        editable={editable}
        label={t("channels.settings.keepFailedRuns")}
        description={t("channels.settings.keepFailedRunsHint")}
        checked={keepFailedRuns}
        onChange={(event) => onChange?.({ keepFailedRuns: event.currentTarget.checked })}
      />
      <SwitchField
        editable={editable}
        label={t("channels.settings.keepTestRuns")}
        description={t("channels.settings.keepTestRunsHint")}
        checked={keepTestRuns}
        onChange={(event) => onChange?.({ keepTestRuns: event.currentTarget.checked })}
      />
    </Stack>
  );
}
