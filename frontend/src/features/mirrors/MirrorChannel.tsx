import { useCan, usePermissions, useTranslate } from "@refinedev/core";
import { ConsoleLink } from "@/components/navigation/ConsoleLink";
import { usePublishedChannelVersion } from "@/features/channels/usePublishedChannelVersion";
import { PublishedTableRunAction } from "@/features/channels/PublishedTableRunAction";
import type { Mirror } from "./types";

export function MirrorChannel({ channelId, version, mirror }: { channelId: string; version: number; mirror: Mirror }) {
  const t = useTranslate();
  const { data } = useCan({ resource: "channels", action: "show" });
  const { data: permissions } = usePermissions<string[]>({});
  const record = usePublishedChannelVersion(channelId, data?.can && Number.isSafeInteger(version) && version > 0 ? version : null, mirror);
  const table = record?.mirror_bindings?.find(item => item.current_reference && item.mirror_id === mirror.id
    && item.source_id === mirror.source_id && item.object_id === mirror.object_id);
  if (!table) return null;
  const nodes = record?.graph?.nodes.filter(node => table.node_ids.includes(node.id)
    && node.type === "read.mirror" && node.config.object_id === mirror.object_id);
  return <>
    <ConsoleLink href={`/console/channels/${encodeURIComponent(channelId)}`}>{t("mirrors.backChannel", { version })}</ConsoleLink>
    {nodes?.map(node => <div key={node.id}>
      {mirror.published_generation_id && mirror.operations?.some(op => op.kind === "open" && op.state === "pending"
        && op.control_revision === mirror.control.control_revision) && ["fail", "skip", "continue"].includes(String(node.config.freshness_policy))
        && <div>{node.name} · {t(`mirrors.policy.${node.config.freshness_policy}`)}</div>}
      {mirror.published_generation_id && permissions?.includes("sources:data_read") && <PublishedTableRunAction channelId={channelId} objectId={mirror.object_id} nodeId={node.id} mode="show" />}
    </div>)}
  </>;
}
