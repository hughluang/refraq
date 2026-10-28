"use client";

import { Code, Table } from "@mantine/core";
import { useCan, useTranslate } from "@refinedev/core";
import { useCallback } from "react";

import { Instant } from "@/components/display/Instant";
import { ListTable } from "@/components/display/ListTable";
import { RowActions } from "@/components/display/RowActions";
import { deleteChannelVariable, listChannelVariables } from "@/features/channels/api";
import { ModuleAction, ModuleId } from "@/features/console/module-identity";
import { useConsolePagedList } from "@/hooks/useConsolePagedList";
import type { PageQuery } from "@/lib/pagination";

const PAGE_SIZE = 50;

export function ChannelVariables({ channelId }: { channelId: string }) {
  const t = useTranslate();
  const { data: canDelete } = useCan({
    resource: ModuleId.channels,
    action: ModuleAction.delete,
  });
  const fetchPage = useCallback(
    (query: PageQuery) => listChannelVariables(channelId, query),
    [channelId],
  );
  const list = useConsolePagedList({
    pageSize: PAGE_SIZE,
    fetch: fetchPage,
    resetDeps: [channelId],
  });
  const { items, reload } = list;

  return (
    <div className="channel-drawer-list">
      <ListTable
        list={list}
        columnCount={5}
        minWidth={640}
        emptyMessage={t("channels.variables.empty")}
        head={
          <Table.Tr>
            <Table.Th>{t("channelVariables.fields.name")}</Table.Th>
            <Table.Th>{t("channelVariables.fields.value")}</Table.Th>
            <Table.Th>{t("channelVariables.fields.expiresAt")}</Table.Th>
            <Table.Th>{t("channelVariables.fields.updatedAt")}</Table.Th>
            <Table.Th />
          </Table.Tr>
        }
      >
        {items.map((row) => (
          <Table.Tr key={row.name}>
            <Table.Td>{row.name}</Table.Td>
            <Table.Td>
              <Code>{JSON.stringify(row.value)}</Code>
            </Table.Td>
            <Table.Td>{row.expires_at ? <Instant value={row.expires_at} /> : "—"}</Table.Td>
            <Table.Td>
              <Instant value={row.updated_at} />
            </Table.Td>
            <Table.Td>
              <RowActions
                recordName={row.name}
                verbs={[
                  {
                    key: "delete",
                    label: t("channels.variables.delete"),
                    color: "red",
                    hidden: !canDelete?.can,
                    action: {
                      safety: "confirm",
                      recordName: row.name,
                      title: t("channels.variables.delete.confirmTitle"),
                      consequence: t("channels.variables.delete.consequence"),
                      confirmLabel: t("channels.variables.delete"),
                      confirmColor: "red",
                      outcome: t("channels.variables.delete.success"),
                      execute: () => deleteChannelVariable(channelId, row.name),
                      onSuccess: () => reload(),
                    },
                  },
                ]}
              />
            </Table.Td>
          </Table.Tr>
        ))}
      </ListTable>
    </div>
  );
}
