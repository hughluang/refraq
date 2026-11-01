"use client";

import { Button, Group, Stack, Text } from "@mantine/core";
import { useTranslate } from "@refinedev/core";
import { useEffect, useRef, useState, type ReactNode } from "react";

import { TextField } from "@/components/form/TextField";

export type MapRow = { id: string; name: string; value: string };

let rowSeq = 0;

function nextRowId(): string {
  rowSeq += 1;
  return `map-row-${rowSeq}`;
}

function asRecord(value: unknown): Record<string, unknown> | null {
  if (typeof value !== "object" || value === null || Array.isArray(value)) return null;
  return value as Record<string, unknown>;
}

function rowsFrom(value: unknown): MapRow[] {
  const record = asRecord(value);
  if (!record) return [];
  return Object.entries(record).map(([name, item]) => ({
    id: nextRowId(),
    name,
    value: typeof item === "string" ? item : "",
  }));
}

function project(rows: readonly MapRow[]): Record<string, string> {
  const out: Record<string, string> = {};
  for (const row of rows) {
    if (row.name === "") continue;
    out[row.name] = row.value;
  }
  return out;
}

function sameMap(rows: readonly MapRow[], value: unknown): boolean {
  const projected = project(rows);
  const stored = asRecord(value) ?? {};
  const left = Object.keys(projected).sort();
  const right = Object.keys(stored)
    .filter((key) => typeof stored[key] === "string")
    .sort();
  if (left.length !== right.length) return false;
  return left.every((key, index) => key === right[index] && projected[key] === stored[key]);
}

export function MapEditor({
  label,
  editable,
  value,
  nameLabel,
  valueLabel,
  renderValue,
  onChange,
}: {
  label: string;
  editable: boolean;
  value: unknown;
  nameLabel: string;
  valueLabel: string;
  renderValue?: (row: MapRow, onValue: (next: string) => void) => ReactNode;
  onChange: (next: Record<string, string>) => void;
}) {
  const t = useTranslate();
  const [rows, setRows] = useState<MapRow[]>(() => rowsFrom(value));
  const rowsRef = useRef(rows);
  rowsRef.current = rows;
  useEffect(() => {
    if (sameMap(rowsRef.current, value)) return;
    setRows(rowsFrom(value));
  }, [value]);

  const commit = (next: MapRow[]) => {
    setRows(next);
    onChange(project(next));
  };

  return (
    <Stack gap="xs" role="group" aria-label={label}>
      <Group justify="space-between">
        <Text size="sm" fw={500}>
          {label}
        </Text>
        {editable ? (
          <Button
            type="button"
            size="xs"
            variant="light"
            onClick={() => commit([...rows, { id: nextRowId(), name: "", value: "" }])}
          >
            {t("channels.config.addItem")}
          </Button>
        ) : null}
      </Group>
      {rows.map((row, index) => (
        <Group key={row.id} align="flex-start" wrap="nowrap">
          <TextField
            editable={editable}
            label={nameLabel}
            value={row.name}
            onChange={(event) => {
              const name = event.currentTarget.value;
              commit(rows.map((item, itemIndex) => (itemIndex === index ? { ...item, name } : item)));
            }}
          />
          {renderValue ? (
            renderValue(row, (next) => {
              commit(rows.map((item, itemIndex) => (itemIndex === index ? { ...item, value: next } : item)));
            })
          ) : (
            <TextField
              editable={editable}
              label={valueLabel}
              value={row.value}
              onChange={(event) => {
                const next = event.currentTarget.value;
                commit(rows.map((item, itemIndex) => (itemIndex === index ? { ...item, value: next } : item)));
              }}
            />
          )}
          {editable ? (
            <Button
              type="button"
              size="xs"
              variant="subtle"
              mt={24}
              onClick={() => commit(rows.filter((item) => item.id !== row.id))}
            >
              {t("channels.config.removeItem")}
            </Button>
          ) : null}
        </Group>
      ))}
    </Stack>
  );
}
