"use client";

import { Badge, Group, Table, Text } from "@mantine/core";
import { useCan, useTranslate } from "@refinedev/core";
import { useCallback, useMemo } from "react";

import { CreateListAction } from "@/components/access/CreateListAction";
import { ListTable } from "@/components/display/ListTable";
import { ListToolbar } from "@/components/display/ListToolbar";
import { RecordReference } from "@/components/display/RecordReference";
import { PageChrome } from "@/components/layout/PageChrome";
import { ModuleAction, ModuleId } from "@/features/console/module-identity";
import { EntityListTagFilter } from "@/features/entities/EntityListTagFilter";
import { EntityRowActions } from "@/features/entities/EntityRowActions";
import { EntityStatusBadge } from "@/features/entities/EntityStatusBadge";
import { PublishStatusBadge } from "@/features/entities/PublishStatusBadge";
import { listEntities } from "@/features/entities/api";
import {
  DEFAULT_ENTITY_LIST_STATUSES,
  entityListRequest,
} from "@/features/entities/entityListFilter";
import { useConsolePagedList } from "@/hooks/useConsolePagedList";
import { useShowInstant } from "@/hooks/useFormatInstant";
import { useListQuery } from "@/hooks/useListQuery";
import type { PageQuery } from "@/lib/pagination";

const PAGE_SIZE = 50;
const NO_TAG_IDS: readonly string[] = [];

export function EntityList() {
  const t = useTranslate();
  const showInstant = useShowInstant();
  const { data: canWrite } = useCan({
    resource: ModuleId.entities,
    action: ModuleAction.edit,
  });
  const query = useListQuery({
    filters: [
      {
        key: "status",
        type: "multi",
        defaultValue: DEFAULT_ENTITY_LIST_STATUSES,
      },
      {
        key: "tag_id",
        type: "multi",
        defaultValue: NO_TAG_IDS,
      },
    ],
  });
  const statusQuery = query.multi("status");
  const tagIds = query.multi("tag_id");

  const fetchPage = useCallback(
    (pageQuery: PageQuery) => {
      const request = entityListRequest({
        q: query.search,
        statuses: statusQuery,
        tagIds,
        limit: pageQuery.limit,
        offset: pageQuery.offset,
      });
      if (request === null) {
        return {
          items: [],
          total: 0,
          limit: pageQuery.limit,
          offset: pageQuery.offset,
        };
      }
      return listEntities(request);
    },
    [query.search, statusQuery, tagIds],
  );

  const list = useConsolePagedList({
    pageSize: PAGE_SIZE,
    fetch: fetchPage,
    resetDeps: [query.search, statusQuery, tagIds],
    filtered: query.isFiltered,
    page: query.page,
    onPageChange: query.setPage,
  });
  const { items } = list;
  const knownTags = useMemo(() => {
    const names = new Map<string, string>();
    for (const row of items) {
      for (const tag of row.tags) names.set(tag.id, tag.name);
    }
    return names;
  }, [items]);

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
      toolbar={
        <ListToolbar
          query={query}
          searchPlaceholder={t("entities.search")}
          filters={[
            {
              key: "status",
              label: t("entities.fields.entityStatus"),
              options: [
                { value: "not_serving", label: t("entities.status.notServing") },
                { value: "serving", label: t("entities.status.serving") },
                { value: "deprecated", label: t("entities.status.deprecated") },
              ],
            },
          ]}
          extra={
            <EntityListTagFilter
              value={tagIds}
              onChange={(ids) => query.setFilter("tag_id", ids)}
              known={knownTags}
            />
          }
        />
      }
    >
      <ListTable
        list={list}
        columnCount={7}
        emptyMessage={t("entities.list.empty")}
        emptyAction={
          <CreateListAction
            resource={ModuleId.entities}
            href="/console/entities/new"
          >
            {t("entities.create")}
          </CreateListAction>
        }
        noMatchMessage={t("entities.list.noMatch")}
        onClearFilters={query.clear}
        head={
          <Table.Tr>
            <Table.Th>{t("entities.fields.name")}</Table.Th>
            <Table.Th>{t("entities.fields.tags")}</Table.Th>
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
                <RecordReference
                  name={row.name}
                  recordKey={row.table_name}
                  href={`/console/entities/${row.id}`}
                />
              </Table.Td>
              <Table.Td>
                {row.tags.length === 0 ? (
                  "—"
                ) : (
                  <Group gap={4} wrap="wrap">
                    {row.tags.map((tag) => (
                      <Badge key={tag.id} size="sm" variant="light" color="gray">
                        {tag.name}
                      </Badge>
                    ))}
                  </Group>
                )}
              </Table.Td>
              <Table.Td>{current ? current.version : "—"}</Table.Td>
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
                  {showInstant(row.updated_at)}
                </Text>
              </Table.Td>
              <Table.Td>
                <EntityRowActions
                  entity={row}
                  canWrite={Boolean(canWrite?.can)}
                  onChanged={() => void list.reload()}
                />
              </Table.Td>
            </Table.Tr>
          );
        })}
      </ListTable>
    </PageChrome>
  );
}
