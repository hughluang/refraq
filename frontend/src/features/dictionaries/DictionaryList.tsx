"use client";

import { Anchor, Button, Group, MultiSelect, Table, Text, TextInput } from "@mantine/core";
import { useTranslate } from "@refinedev/core";
import Link from "next/link";
import { useCallback, useState } from "react";

import { CreateListAction } from "@/components/access/CreateListAction";
import { ListTable } from "@/components/display/ListTable";
import { PageChrome } from "@/components/layout/PageChrome";
import { ModuleId } from "@/features/console/module-identity";
import { listDictionaries } from "@/features/dictionaries/api";
import { DictionaryStatusBadge } from "@/features/dictionaries/DictionaryStatusBadge";
import {
  DEFAULT_DICTIONARY_LIST_STATUSES,
  dictionaryListIsFiltered,
  type DictionaryListStatus,
} from "@/features/dictionaries/dictionaryListFilter";
import { useConsolePagedList } from "@/hooks/useConsolePagedList";
import { useFormatInstant } from "@/hooks/useFormatInstant";
import type { PageQuery } from "@/lib/pagination";

const PAGE_SIZE = 50;

export function DictionaryList() {
  const t = useTranslate();
  const formatInstant = useFormatInstant();
  const [q, setQ] = useState("");
  const [statuses, setStatuses] = useState<DictionaryListStatus[]>([
    ...DEFAULT_DICTIONARY_LIST_STATUSES,
  ]);

  const fetchPage = useCallback(
    (query: PageQuery) => {
      if (statuses.length === 0) {
        return {
          items: [],
          total: 0,
          limit: query.limit,
          offset: query.offset,
        };
      }
      return listDictionaries({
        q: q.trim() || undefined,
        status: statuses,
        ...query,
      });
    },
    [q, statuses],
  );

  const filtered = dictionaryListIsFiltered(q, statuses);
  const list = useConsolePagedList({
    pageSize: PAGE_SIZE,
    fetch: fetchPage,
    resetDeps: [q, statuses],
    filtered,
  });

  return (
    <PageChrome
      title={t("dictionaries.title")}
      description={t("dictionaries.description")}
      actions={
        <CreateListAction
          resource={ModuleId.dictionaries}
          href="/console/dictionaries/new"
        >
          {t("dictionaries.create")}
        </CreateListAction>
      }
    >
      <Group>
        <TextInput
          placeholder={t("dictionaries.search")}
          value={q}
          onChange={(event) => setQ(event.currentTarget.value)}
          w={280}
        />
        <MultiSelect
          placeholder={
            statuses.length === 0 ? t("dictionaries.fields.status") : undefined
          }
          data={[
            { value: "available", label: t("dictionaries.status.available") },
            { value: "deprecated", label: t("dictionaries.status.deprecated") },
          ]}
          value={statuses}
          onChange={(value) => setStatuses(value as DictionaryListStatus[])}
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
              setStatuses([...DEFAULT_DICTIONARY_LIST_STATUSES]);
            }}
          >
            {t("common.filters.clear")}
          </Button>
        ) : null}
      </Group>
      <ListTable
        list={list}
        columnCount={5}
        emptyMessage={t("dictionaries.list.empty")}
        noMatchMessage={t("dictionaries.list.noMatch")}
        head={
          <Table.Tr>
            <Table.Th>{t("dictionaries.fields.name")}</Table.Th>
            <Table.Th>{t("dictionaries.fields.displayName")}</Table.Th>
            <Table.Th>{t("dictionaries.fields.revision")}</Table.Th>
            <Table.Th>{t("dictionaries.fields.status")}</Table.Th>
            <Table.Th>{t("entities.fields.updatedAt")}</Table.Th>
          </Table.Tr>
        }
      >
        {list.items.map((row) => (
          <Table.Tr key={row.id}>
            <Table.Td>
              <Anchor
                component={Link}
                href={`/console/dictionaries/${row.id}`}
                size="sm"
                ff="monospace"
              >
                {row.name}
              </Anchor>
            </Table.Td>
            <Table.Td>{row.display_name}</Table.Td>
            <Table.Td>{row.revision}</Table.Td>
            <Table.Td>
              <DictionaryStatusBadge deprecated={row.deprecated_at != null} />
            </Table.Td>
            <Table.Td>
              <Text size="sm" c="dimmed">
                {formatInstant(row.updated_at)}
              </Text>
            </Table.Td>
          </Table.Tr>
        ))}
      </ListTable>
    </PageChrome>
  );
}
