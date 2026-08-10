"use client";

import {
  Badge,
  Button,
  Group,
  NumberInput,
  Stack,
  Table,
  Text,
  Textarea,
} from "@mantine/core";
import { useNotification, useTranslate } from "@refinedev/core";
import { useEffect, useMemo, useState } from "react";

import { runSourceQuery } from "@/features/sources/api";
import type {
  CatalogObject,
  QueryResult,
  Source,
} from "@/features/sources/types";
import { ApiError } from "@/lib/api";

type SampleTabProps = {
  object: CatalogObject;
  source: Source | null;
};

function quoteIdent(engine: string | null | undefined, name: string): string {
  if (engine === "mssql") return `[${name.replaceAll("]", "]]")}]`;
  if (engine === "oracle") return `"${name.replaceAll('"', '""')}"`;
  return `"${name.replaceAll('"', '""')}"`;
}

function buildDefaultSql(
  object: CatalogObject,
  engine: string | null | undefined,
  maxRows: number,
): string {
  const schema = quoteIdent(engine, object.schema_name);
  const table = quoteIdent(engine, object.name);
  const qualified = `${schema}.${table}`;
  if (engine === "mssql") {
    return `SELECT TOP (${maxRows}) * FROM ${qualified}`;
  }
  if (engine === "oracle") {
    return `SELECT * FROM ${qualified} FETCH FIRST ${maxRows} ROWS ONLY`;
  }
  return `SELECT * FROM ${qualified} LIMIT ${maxRows}`;
}

export function SampleTab({ object, source }: SampleTabProps) {
  const t = useTranslate();
  const { open } = useNotification();
  const [maxRows, setMaxRows] = useState(50);
  const [sql, setSql] = useState("");
  const [result, setResult] = useState<QueryResult | null>(null);
  const [forbidden, setForbidden] = useState(false);
  const [running, setRunning] = useState(false);

  const defaultSql = useMemo(
    () => buildDefaultSql(object, source?.engine, maxRows),
    [object, source?.engine, maxRows],
  );

  useEffect(() => {
    setSql(defaultSql);
    setResult(null);
    setForbidden(false);
  }, [defaultSql]);

  const run = async () => {
    if (!source) return;
    setRunning(true);
    try {
      const data = await runSourceQuery(source.id, {
        sql,
        max_rows: maxRows,
      });
      setResult(data);
      setForbidden(false);
    } catch (err) {
      if (err instanceof ApiError && err.status === 403) {
        setForbidden(true);
        setResult(null);
        return;
      }
      open?.({
        type: "error",
        message: err instanceof ApiError ? err.detail : String(err),
      });
    } finally {
      setRunning(false);
    }
  };

  if (forbidden) {
    return (
      <Text size="sm" c="dimmed">
        {t("catalog.sample.forbidden")}
      </Text>
    );
  }

  return (
    <Stack gap="sm">
      <Group align="flex-end">
        <NumberInput
          label={t("catalog.sample.maxRows")}
          value={maxRows}
          onChange={(v) => setMaxRows(typeof v === "number" ? v : 50)}
          min={1}
          max={500}
          w={140}
        />
        <Button loading={running} onClick={() => void run()}>
          {t("catalog.sample.run")}
        </Button>
      </Group>
      <Textarea
        label={t("catalog.sample.sql")}
        value={sql}
        onChange={(e) => setSql(e.currentTarget.value)}
        minRows={3}
        autosize
      />
      {!result ? (
        <Text size="sm" c="dimmed">
          {t("catalog.sample.empty")}
        </Text>
      ) : (
        <Stack gap="xs">
          <Group gap="sm">
            <Text size="sm" c="dimmed">
              {t("catalog.sample.duration", { ms: result.duration_ms })}
            </Text>
            {result.truncated ? (
              <Badge color="yellow">{t("catalog.sample.truncated")}</Badge>
            ) : null}
          </Group>
          <Table striped highlightOnHover withTableBorder>
            <Table.Thead>
              <Table.Tr>
                {result.columns.map((col) => (
                  <Table.Th key={col}>
                    <Text size="sm">{col}</Text>
                  </Table.Th>
                ))}
              </Table.Tr>
            </Table.Thead>
            <Table.Tbody>
              {result.rows.map((row, rowIdx) => (
                <Table.Tr key={rowIdx}>
                  {row.map((cell, cellIdx) => (
                    <Table.Td key={`${rowIdx}-${cellIdx}`}>
                      <Text size="xs" style={{ whiteSpace: "pre-wrap" }}>
                        {cell === null || cell === undefined
                          ? "NULL"
                          : String(cell)}
                      </Text>
                    </Table.Td>
                  ))}
                </Table.Tr>
              ))}
            </Table.Tbody>
          </Table>
        </Stack>
      )}
    </Stack>
  );
}
