"use client";

import { Group, Stack, Text } from "@mantine/core";
import { useTranslate } from "@refinedev/core";
import { ConsoleLink } from "@/components/navigation/ConsoleLink";
import type { CatalogJoin, CatalogObject } from "@/features/sources/types";
import { objectRefFromColumnLocator } from "./joinEdges";

function endpoint(object: CatalogObject, id: string, locator?: string | null) {
  const column = object.columns.find((item) => item.id === id);
  if (column) {
    return {
      label: `${object.name}.${column.name}`,
      context: `${object.schema_name} · ${object.locator_key}`,
      href: object.id,
    };
  }
  const parts = locator?.split("/");
  const href = objectRefFromColumnLocator(locator);
  if (parts && href) {
    return {
      label: `${parts[5]}.${parts[7]}`,
      context: `${parts[2]} · ${parts[3]}`,
      href,
    };
  }
  return { label: locator || id, context: "", href: null };
}

export function relationName(object: CatalogObject, join: CatalogJoin) {
  const from = endpoint(object, join.from_column_id, join.from_column_locator_key);
  const to = endpoint(object, join.to_column_id, join.to_column_locator_key);
  return `${from.label} → ${to.label}`;
}

export function RelationSummary({ object, join, compact = false }: { object: CatalogObject; join: CatalogJoin; compact?: boolean }) {
  const t = useTranslate();
  const from = endpoint(object, join.from_column_id, join.from_column_locator_key);
  const to = endpoint(object, join.to_column_id, join.to_column_locator_key);

  return (
    <Stack gap={4} style={{ minWidth: 0 }}>
      <Group gap="sm" align="flex-start" wrap={compact ? "nowrap" : "wrap"}>
        {[from, to].map((item, index) => (
          <Group key={index} gap="sm" align="flex-start" wrap="nowrap" style={{ minWidth: 0 }}>
            {index === 1 ? <Text aria-label={t("catalog.joins.storedDirection")}>→</Text> : null}
            <Stack gap={2} style={{ minWidth: 0, overflowWrap: "anywhere" }}>
              {item.href ? (
                <Text
                  component={ConsoleLink}
                  href={`/console/catalog/${encodeURIComponent(item.href)}`}
                  size="sm"
                  style={compact ? { whiteSpace: "nowrap" } : undefined}
                  fw={500}
                >
                  {item.label}
                </Text>
              ) : (
                <Text size="sm" fw={500}>{item.label}</Text>
              )}
              {!compact ? <Text size="xs" c="dimmed">{item.context}</Text> : null}
            </Stack>
          </Group>
        ))}
      </Group>
    </Stack>
  );
}
