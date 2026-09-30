"use client";

import { Anchor, Badge, Group, Table, Text, TextInput } from "@mantine/core";
import { useTranslate } from "@refinedev/core";
import Link from "next/link";
import { useCallback, useState } from "react";

import { CreateListAction } from "@/components/access/CreateListAction";
import { ListTable } from "@/components/display/ListTable";
import { PageChrome } from "@/components/layout/PageChrome";
import { listDictionaries } from "@/features/dictionaries/api";
import { ModuleId } from "@/features/console/module-identity";
import { useConsolePagedList } from "@/hooks/useConsolePagedList";
import { useFormatInstant } from "@/hooks/useFormatInstant";
import type { PageQuery } from "@/lib/pagination";

const PAGE_SIZE = 50;

export function DictionaryList() {
  const t = useTranslate();
  const formatInstant = useFormatInstant();
  const [q, setQ] = useState("");

  const fetchPage = useCallback(
    (query: PageQuery) =>
      listDictionaries({
        q: q.trim() || undefined,
        ...query,
      }),
    [q],
  );

  const filtered = q.trim() !== "";
  const list = useConsolePagedList({
    pageSize: PAGE_SIZE,
    fetch: fetchPage,
    resetDeps: [q],
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
            <Table.Th>{t("dictionaries.fields.deprecated")}</Table.Th>
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
              {row.deprecated_at ? (
                <Badge color="gray" variant="light">
                  {t("dictionaries.fields.deprecated")}
                </Badge>
              ) : null}
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
