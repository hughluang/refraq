"use client";

import { Code, Table } from "@mantine/core";
import { useCan, useTranslate } from "@refinedev/core";

import { Instant } from "@/components/display/Instant";
import { ListTable } from "@/components/display/ListTable";
import { RowActions } from "@/components/display/RowActions";
import { PageChrome } from "@/components/layout/PageChrome";
import { ModuleAction, ModuleId } from "@/features/console/module-identity";
import { useConsolePagedList } from "@/hooks/useConsolePagedList";
import { useListQuery } from "@/hooks/useListQuery";
import { apiClient } from "@/lib/api";
import type { OffsetPage } from "@/lib/pagination";

type Variable = {
  name: string;
  value: unknown;
  expires_at: string | null;
  updated_at: string;
};

async function listVariables(query: { limit: number; offset: number }): Promise<OffsetPage<Variable>> {
  const params = new URLSearchParams({
    limit: String(query.limit),
    offset: String(query.offset),
  });
  return apiClient<OffsetPage<Variable>>(`/channel-variables?${params.toString()}`);
}

async function deleteVariable(name: string): Promise<void> {
  await apiClient(`/channel-variables/${encodeURIComponent(name)}`, { method: "DELETE" });
}

export function ChannelVariableList() {
  const t = useTranslate();
  const { data: canDelete } = useCan({
    resource: ModuleId.channelVariables,
    action: ModuleAction.delete,
  });
  const query = useListQuery({ search: false });
  const list = useConsolePagedList<Variable>({
    pageSize: 50,
    fetch: listVariables,
    page: query.page,
    onPageChange: query.setPage,
  });
  const { items, reload } = list;

  return (
    <PageChrome title={t("channelVariables.title")}>
      <ListTable
        list={list}
        columnCount={5}
        emptyMessage={t("channelVariables.empty")}
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
                    label: t("channelVariables.delete"),
                    color: "red",
                    hidden: !canDelete?.can,
                    action: {
                      safety: "confirm",
                      recordName: row.name,
                      title: t("channelVariables.delete.confirmTitle"),
                      consequence: t("channelVariables.delete.consequence"),
                      confirmLabel: t("channelVariables.delete"),
                      confirmColor: "red",
                      outcome: t("channelVariables.delete.success"),
                      execute: () => deleteVariable(row.name),
                      onSuccess: () => reload(),
                    },
                  },
                ]}
              />
            </Table.Td>
          </Table.Tr>
        ))}
      </ListTable>
    </PageChrome>
  );
}
