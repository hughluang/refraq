"use client";

import { Button, Code, Table } from "@mantine/core";
import { CanAccess, useNotification, useTranslate } from "@refinedev/core";
import { useCallback } from "react";

import { Instant } from "@/components/display/Instant";
import { ListTable } from "@/components/display/ListTable";
import { ConfirmActionModal } from "@/components/feedback/ConfirmActionModal";
import { PageChrome } from "@/components/layout/PageChrome";
import { ModuleAction, ModuleId } from "@/features/console/module-identity";
import { useConfirmAction } from "@/hooks/useConfirmAction";
import { useConsolePagedList } from "@/hooks/useConsolePagedList";
import { apiClient } from "@/lib/api";
import type { Instant as InstantValue } from "@/lib/instant";
import type { OffsetPage } from "@/lib/pagination";
import { problemMessage } from "@/lib/problem";

type Variable = {
  name: string;
  value: unknown;
  expires_at: InstantValue | null;
  updated_at: InstantValue;
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
  const { open } = useNotification();
  const list = useConsolePagedList<Variable>({
    pageSize: 50,
    fetch: listVariables,
  });
  const { items, reload } = list;
  const confirm = useConfirmAction<Variable>();

  const remove = useCallback(async () => {
    const row = confirm.pending;
    if (!row) return;
    try {
      await deleteVariable(row.name);
      open?.({ type: "success", message: t("channelVariables.delete.success") });
      confirm.close();
      await reload();
    } catch (err) {
      open?.({ type: "error", message: problemMessage(t, err, String(err)) });
    }
  }, [confirm, open, reload, t]);

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
              <CanAccess resource={ModuleId.channelVariables} action={ModuleAction.delete}>
                <Button size="xs" color="red" variant="light" onClick={() => confirm.open(row)}>
                  {t("channelVariables.delete")}
                </Button>
              </CanAccess>
            </Table.Td>
          </Table.Tr>
        ))}
      </ListTable>
      <ConfirmActionModal
        opened={confirm.opened}
        onClose={confirm.close}
        title={t("channelVariables.delete.confirmTitle")}
        body={t("channelVariables.delete.confirmBody", { name: confirm.pending?.name ?? "" })}
        confirmColor="red"
        onConfirm={() => void remove()}
      />
    </PageChrome>
  );
}
