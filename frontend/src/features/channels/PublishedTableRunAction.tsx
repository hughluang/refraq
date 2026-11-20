"use client";

import { Button } from "@mantine/core";
import { useCan, useTranslate } from "@refinedev/core";

import { ConsoleLink } from "@/components/navigation/ConsoleLink";
import { ModuleAction, ModuleId } from "@/features/console/module-identity";

export type TableSelection = { objectId: string; nodeId: string };

export function PublishedTableRunAction({ channelId, objectId, nodeId, mode, onRun }: TableSelection & {
  channelId: string; mode: "show" | "edit"; onRun?: (table: TableSelection) => void;
}) {
  const t = useTranslate();
  const { data } = useCan({ resource: ModuleId.channels, action: ModuleAction.edit });
  if (!data?.can) return null;
  const label = t("channels.verify.run");
  if (mode === "show") {
    const query = new URLSearchParams({ verifyObject: objectId, verifyNode: nodeId });
    return <Button variant="light" size="xs" component={ConsoleLink} href={`/console/channels/${encodeURIComponent(channelId)}/edit?${query}`}>{label}</Button>;
  }
  return <Button variant="light" size="xs" disabled={!onRun} onClick={() => onRun?.({ objectId, nodeId })}>{label}</Button>;
}
