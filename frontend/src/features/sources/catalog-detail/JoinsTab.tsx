"use client";

import { Badge, Button, Drawer, Group, Stack, Table, Text } from "@mantine/core";
import { useTranslate } from "@refinedev/core";
import { useCallback, useLayoutEffect, useRef, useState } from "react";
import { Instant } from "@/components/display/Instant";
import { ListTable } from "@/components/display/ListTable";
import { FillColumn } from "@/components/layout/FillColumn";
import { SectionHeader } from "@/components/layout/SectionHeader";
import { listObjectJoins } from "@/features/sources/api/joins";
import type { CatalogJoin, CatalogObject } from "@/features/sources/types";
import { useConsolePagedList } from "@/hooks/useConsolePagedList";
import type { PageQuery } from "@/lib/pagination";
import { RelationActions } from "./RelationActions";
import { RelationPathsDrawer } from "./RelationPathsDrawer";
import { RelationSummary } from "./RelationSummary";
import { RelationFormDialog } from "./RelationFormDialog";

type JoinsTabProps = { object: CatalogObject; writable: boolean; listEnabled?: boolean };

export function JoinsTab({ object, writable, listEnabled = true }: JoinsTabProps) {
  const t = useTranslate();
  const [session, setSession] = useState<{ join?: CatalogJoin } | null>(null);
  const [inspected, setInspected] = useState<CatalogJoin | null>(null);
  const [pathDrawerOpen, setPathDrawerOpen] = useState(false);
  const fetchPage = useCallback((query: PageQuery) => listObjectJoins(object.id, query), [object.id]);
  const list = useConsolePagedList({ pageSize: 50, fetch: fetchPage, resetDeps: [object.id], enabled: listEnabled });
  const { items: joins, reload } = list;
  const rowsRef = useRef(new Map<string, HTMLTableRowElement>());
  const [returnToJoin, setReturnToJoin] = useState<string | null>(null);
  useLayoutEffect(() => {
    if (!returnToJoin || list.loading || session) return;
    rowsRef.current.get(returnToJoin)?.querySelector<HTMLButtonElement>('[data-row-action="amend"]')?.focus();
    setReturnToJoin(null);
  }, [returnToJoin, list.loading, session, joins]);

  const addAction = writable ? (
    <Button size="sm" onClick={() => setSession({})}>
      {t("catalog.joins.add")}
    </Button>
  ) : null;

  return (
    <FillColumn gap="sm">
      <div style={{ flexShrink: 0 }}>
        <SectionHeader
          title={t("catalog.joins.title")}
          order={4}
          actions={
            <Group gap="xs" align="flex-end">
              <Button size="sm" variant="default" onClick={() => setPathDrawerOpen(true)}>
                {t("catalog.joins.path.explore")}
              </Button>
              {addAction}
            </Group>
          }
        />
      </div>
      <ListTable
        list={list}
        columnCount={4}
        minWidth={760}
        emptyMessage={t("catalog.joins.empty")}
        emptyAction={addAction}
        head={
          <Table.Tr>
            <Table.Th>{t("catalog.joins.endpoints")}</Table.Th>
            <Table.Th>{t("catalog.joins.kind")}</Table.Th>
            <Table.Th>{t("catalog.joins.state")}</Table.Th>
            <Table.Th />
          </Table.Tr>
        }
      >
        {joins.map((join) => (
          <Table.Tr key={join.id} ref={(node) => {
            if (node) rowsRef.current.set(join.id, node);
            else rowsRef.current.delete(join.id);
          }}>
            <Table.Td><RelationSummary object={object} join={join} compact /></Table.Td>
            <Table.Td>{join.join_kind ?? "INNER"}</Table.Td>
            <Table.Td>
              <Stack gap={4}>
                {join.is_rejected ? (
                  <Badge size="xs" color="red">{t("catalog.joins.state.rejected")}</Badge>
                ) : null}
                <Text size="xs" c="dimmed">
                  {t(join.created_by_user_id ? "catalog.joins.state.manual" : "catalog.joins.state.automated")}
                </Text>
              </Stack>
            </Table.Td>
            <Table.Td>
              <RelationActions
                object={object}
                join={join}
                writable={writable}
                onInspect={() => setInspected(join)}
                onAmend={() => setSession({ join })}
                onChanged={reload}
              />
            </Table.Td>
          </Table.Tr>
        ))}
      </ListTable>
      {writable && session ? (
        <RelationFormDialog
          key={`${object.id}:${session.join?.id ?? "new"}`}
          object={object}
          join={session.join}
          onClose={() => setSession(null)}
          onSaved={async () => {
            const editedId = session.join?.id;
            setSession(null);
            await reload();
            if (editedId) setReturnToJoin(editedId);
          }}
        />
      ) : null}
      <Drawer
        opened={inspected != null}
        onClose={() => setInspected(null)}
        title={t("catalog.joins.inspect")}
        position="right"
        size="md"
      >
        {inspected ? (
          <Stack gap="md">
            <RelationSummary object={object} join={inspected} />
            <Text size="sm" c="dimmed">{t("catalog.joins.storedDirection")}</Text>
            <Text size="sm">{t("catalog.joins.kind")}: {inspected.join_kind ?? "INNER"}</Text>
            <Stack gap={4}>
              <Text fw={500} size="sm">{t("catalog.joins.expression")}</Text>
              <Text size="sm" style={{ whiteSpace: "pre-wrap", overflowWrap: "anywhere" }}>
                {inspected.join_expression ?? "—"}
              </Text>
            </Stack>
            <Stack gap={4}>
              <Text fw={500} size="sm">{t("catalog.joins.evidence")}</Text>
              <Text size="sm" style={{ whiteSpace: "pre-wrap", overflowWrap: "anywhere" }}>
                {inspected.evidence}
              </Text>
            </Stack>
            <details>
              <summary>{t("catalog.joins.locators")}</summary>
              <Text size="xs" style={{ overflowWrap: "anywhere" }}>
                {inspected.from_column_locator_key ?? inspected.from_column_id} → {inspected.to_column_locator_key ?? inspected.to_column_id}
              </Text>
            </details>
            <Text size="sm">{t("catalog.joins.createdAt")}: <Instant value={inspected.created_at} /></Text>
          </Stack>
        ) : null}
      </Drawer>
      {pathDrawerOpen ? (
        <RelationPathsDrawer key={object.id} start={object.id} onClose={() => setPathDrawerOpen(false)} />
      ) : null}
    </FillColumn>
  );
}
