"use client";

import { Text } from "@mantine/core";
import { ConsoleLink } from "@/components/navigation/ConsoleLink";

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
  const channelId = task.target?.channel_id;
  return (
    <>
      <Text size="sm">
        {channelId ? (
          <ConsoleLink href={`/console/channels/${channelId}`}>{identity.primary}</ConsoleLink>
        ) : (
          identity.primary
        )}
      </Text>
      {identity.customName ? (
        <Text size="xs" c="dimmed">
          {identity.customName}
        </Text>
      ) : null}
    </>
  );
}
