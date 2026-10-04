"use client";

import { Text } from "@mantine/core";

import {
  scheduleIdentity,
  type ScheduleIdentityInput,
  type ScheduleIdentityScope,
} from "@/features/schedules/scheduleIdentity";

export function ScheduleIdentityCell({
  task,
  scope,
}: {
  task: ScheduleIdentityInput;
  scope: ScheduleIdentityScope;
}) {
  const identity = scheduleIdentity(task, scope);
  return (
    <>
      <Text size="sm">{identity.primary}</Text>
      {identity.customName ? (
        <Text size="xs" c="dimmed">
          {identity.customName}
        </Text>
      ) : null}
    </>
  );
}
