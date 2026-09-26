"use client";

import { Button, Group, MultiSelect, Table, Text, TextInput } from "@mantine/core";
import { useTranslate } from "@refinedev/core";
import Link from "next/link";
import { useCallback, useState } from "react";

import { CreateListAction } from "@/components/access/CreateListAction";
import { ListTable } from "@/components/display/ListTable";
import { PageChrome } from "@/components/layout/PageChrome";
import { ModuleId } from "@/features/console/module-identity";
import { EntityStatusBadge } from "@/features/entities/EntityStatusBadge";
import { PublishStatusBadge } from "@/features/entities/PublishStatusBadge";
import { listEntities } from "@/features/entities/api";
import {
  DEFAULT_ENTITY_LIST_STATUSES,
  entityListIsFiltered,
  entityListShouldFetch,
  entityListStatuses,
} from "@/features/entities/entityListFilter";
import type { EntityStatus } from "@/features/entities/publishStatus";
import { useConsolePagedList } from "@/hooks/useConsolePagedList";
import { useFormatInstant } from "@/hooks/useFormatInstant";
import type { PageQuery } from "@/lib/pagination";

const PAGE_SIZE = 50;

export function EntityList() {
  const t = useTranslate();
  const formatInstant = useFormatInstant();
  const [q, setQ] = useState("");
  const [statuses, setStatuses] = useState<EntityStatus[]>([
    ...DEFAULT_ENTITY_LIST_STATUSES,
  ]);

  const fetchPage = useCallback(
    (query: PageQuery) => {
      if (!entityListShouldFetch(statuses)) {
        return {
          items: [],
          total: 0,
          limit: query.limit,
          offset: query.offset,
        };
      }
      return listEntities({
        q: q.trim() || undefined,
        status: statuses,
        ...query,
      });
    },
    [q, statuses],
  );

  const filtered = entityListIsFiltered(q, statuses);
  const list = useConsolePagedList({
    pageSize: PAGE_SIZE,
    fetch: fetchPage,
    resetDeps: [q, statuses],
    filtered,
  });
  const { items } = list;

  return (
    <PageChrome
      title={t("entities.title")}
      description={t("entities.description")}
      actions={
        <CreateListAction
          resource={ModuleId.entities}
          href="/console/entities/new"
        >
          {t("entities.create")}
        </CreateListAction>
      }
    >
      <Group>
        <TextInput
          placeholder={t("entities.search")}
          value={q}
          onChange={(event) => setQ(event.currentTarget.value)}
          w={280}
        />
        <MultiSelect
          placeholder={
            statuses.length === 0
              ? t("entities.fields.entityStatus")
              : undefined
          }
          data={[
            { value: "not_serving", label: t("entities.status.notServing") },
            { value: "serving", label: t("entities.status.serving") },
            { value: "deprecated", label: t("entities.status.deprecated") },
          ]}
          value={statuses}
          onChange={(value) => setStatuses(entityListStatuses(value))}
          searchable={false}
          clearable
          w="max-content"
          miw={280}
          styles={{
            root: { flexShrink: 0 },
            wrapper: { width: "max-content" },
            input: { width: "max-content", minWidth: 280 },
            pillsList: { flexWrap: "nowrap" },
            pill: { flexShrink: 0, maxWidth: "none" },
          }}
        />
        {filtered ? (
          <Button
            variant="subtle"
            size="xs"
            onClick={() => {
              setQ("");
              setStatuses([...DEFAULT_ENTITY_LIST_STATUSES]);
            }}
          >
            {t("common.filters.clear")}
          </Button>
        ) : null}
      </Group>
      <ListTable
        list={list}
        columnCount={7}
        emptyMessage={t("entities.list.empty")}
        noMatchMessage={t("entities.list.noMatch")}
        head={
          <Table.Tr>
            <Table.Th>{t("entities.fields.tableName")}</Table.Th>
            <Table.Th>{t("entities.fields.name")}</Table.Th>
            <Table.Th>{t("entities.fields.version")}</Table.Th>
            <Table.Th>{t("entities.fields.entityStatus")}</Table.Th>
            <Table.Th>{t("entities.fields.versionStatus")}</Table.Th>
            <Table.Th>{t("entities.fields.updatedAt")}</Table.Th>
            <Table.Th />
          </Table.Tr>
        }
      >
        {items.map((row) => {
          const current = row.current_version;
          return (
            <Table.Tr key={row.id}>
              <Table.Td>
                <Text ff="monospace" size="sm">
                  {row.table_name}
                </Text>
              </Table.Td>
              <Table.Td>{row.name}</Table.Td>
              <Table.Td>{current ? `v${current.version}` : "—"}</Table.Td>
              <Table.Td>
                <EntityStatusBadge entity={row} />
              </Table.Td>
              <Table.Td>
                {current ? (
                  <PublishStatusBadge publishStatus={current.publish_status} />
                ) : (
                  "—"
                )}
              </Table.Td>
              <Table.Td>
                <Text size="sm" c="dimmed">
                  {formatInstant(row.updated_at)}
                </Text>
              </Table.Td>
              <Table.Td>
                <Button
                  component={Link}
                  href={`/console/entities/${row.id}`}
                  size="xs"
                  variant="light"
                >
                  {t("actions.show")}
                </Button>
              </Table.Td>
            </Table.Tr>
          );
        })}
      </ListTable>
    </PageChrome>
  );
}
