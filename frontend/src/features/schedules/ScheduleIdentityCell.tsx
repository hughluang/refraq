"use client";

import { Text } from "@mantine/core";
import Link from "next/link";

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
          <Link href={`/console/channels/${channelId}`}>{identity.primary}</Link>
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
