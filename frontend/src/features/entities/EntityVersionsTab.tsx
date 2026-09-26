"use client";

import { Button, Group, Table, Text } from "@mantine/core";
import { useTranslate } from "@refinedev/core";

import { PublishStatusBadge } from "@/features/entities/PublishStatusBadge";
import type { BusinessEntity, EntityVersion } from "@/features/entities/types";

type Props = {
  entity: BusinessEntity;
  versions: EntityVersion[];
  canDropTable: boolean;
  busy: boolean;
  onDrop: (version: EntityVersion) => void;
};

function canDropVersion(entity: BusinessEntity, version: EntityVersion): boolean {
  if (!version.alignment.table_present || !version.table_name) {
    return false;
  }
  if (entity.deprecated_at) {
    return true;
  }
  return version.table_name !== entity.table_name;
}

export function EntityVersionsTab({
  entity,
  versions,
  canDropTable,
  busy,
  onDrop,
}: Props) {
  const t = useTranslate();

  return (
    <Table withTableBorder>
      <Table.Thead>
        <Table.Tr>
          <Table.Th>{t("entities.fields.version")}</Table.Th>
          <Table.Th>{t("entities.fields.tableName")}</Table.Th>
          <Table.Th>{t("entities.fields.versionStatus")}</Table.Th>
          <Table.Th />
        </Table.Tr>
      </Table.Thead>
      <Table.Tbody>
        {versions.map((version) => (
          <Table.Tr key={version.id}>
            <Table.Td>v{version.version}</Table.Td>
            <Table.Td>
              <Text ff="monospace" size="sm">
                {version.table_name ?? "—"}
              </Text>
            </Table.Td>
            <Table.Td>
              <PublishStatusBadge publishStatus={version.publish_status} />
            </Table.Td>
            <Table.Td>
              <Group gap="xs" justify="flex-end">
                {canDropTable && canDropVersion(entity, version) ? (
                  <Button
                    size="xs"
                    color="red"
                    variant="light"
                    onClick={() => onDrop(version)}
                    loading={busy}
                  >
                    {t("entities.drop")}
                  </Button>
                ) : null}
              </Group>
            </Table.Td>
          </Table.Tr>
        ))}
      </Table.Tbody>
    </Table>
  );
}
