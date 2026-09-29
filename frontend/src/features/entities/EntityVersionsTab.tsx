"use client";

import { Button, Drawer, Group, Stack, Table, Text } from "@mantine/core";
import { useTranslate } from "@refinedev/core";
import { useState } from "react";

import { DisplayField } from "@/components/display/DisplayField";
import { EmptyState } from "@/components/feedback/EmptyState";
import { attributeConfigSummary } from "@/features/entities/attributeDraftValidation";
import { getVersion } from "@/features/entities/api";
import {
  draftsFromVersion,
  referenceSummaryLabel,
} from "@/features/entities/entityPresentation";
import { physicalColumnType } from "@/features/entities/physicalType";
import { PublishStatusBadge } from "@/features/entities/PublishStatusBadge";
import type {
  AttributeDraft,
  BusinessEntity,
  EntityVersion,
} from "@/features/entities/types";
import { JobStatusBadge } from "@/features/jobs/JobStatusBadge";

type Props = {
  entity: BusinessEntity;
  versions: EntityVersion[];
  canDropTable: boolean;
  busy: boolean;
  formatInstant: (value: string | null | undefined) => string;
  onOpenJob: (jobId: string | null) => void;
  onViewError: (err: unknown) => void;
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
  formatInstant,
  onOpenJob,
  onViewError,
  onDrop,
}: Props) {
  const t = useTranslate();
  const [viewingId, setViewingId] = useState<string | null>(null);
  const [opened, setOpened] = useState<EntityVersion | null>(null);

  const view = async (version: EntityVersion) => {
    setViewingId(version.id);
    try {
      const res = await getVersion(entity.id, version.id);
      setOpened(res.version);
    } catch (err) {
      onViewError(err);
    } finally {
      setViewingId(null);
    }
  };

  return (
    <>
      <Table withTableBorder>
        <Table.Thead>
          <Table.Tr>
            <Table.Th>{t("entities.fields.version")}</Table.Th>
            <Table.Th>{t("entities.fields.tableName")}</Table.Th>
            <Table.Th>{t("entities.fields.versionStatus")}</Table.Th>
            <Table.Th>{t("entities.fields.attributeCount")}</Table.Th>
            <Table.Th>{t("entities.fields.createdAt")}</Table.Th>
            <Table.Th>{t("entities.fields.publishJob")}</Table.Th>
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
              <Table.Td>{version.attribute_count}</Table.Td>
              <Table.Td>{formatInstant(version.created_at)}</Table.Td>
              <Table.Td>
                {version.alignment.latest_job_id &&
                version.alignment.latest_job_status ? (
                  <PublishJobCell
                    jobId={version.alignment.latest_job_id}
                    status={version.alignment.latest_job_status}
                    onOpenJob={onOpenJob}
                  />
                ) : (
                  "—"
                )}
              </Table.Td>
              <Table.Td>
                <Group gap="xs" justify="flex-end">
                  <Button
                    size="xs"
                    variant="light"
                    onClick={() => void view(version)}
                    loading={viewingId === version.id}
                  >
                    {t("entities.versions.view")}
                  </Button>
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
      <Drawer
        opened={opened != null}
        onClose={() => setOpened(null)}
        position="right"
        size="xl"
        title={opened ? `v${opened.version}` : ""}
      >
        {opened ? (
          <VersionShape
            entity={entity}
            version={opened}
          />
        ) : null}
      </Drawer>
    </>
  );
}

function PublishJobCell({
  jobId,
  status,
  onOpenJob,
}: {
  jobId: string;
  status: string;
  onOpenJob: (jobId: string | null) => void;
}) {
  return (
    <Button
      variant="subtle"
      size="compact-xs"
      px={0}
      onClick={() => onOpenJob(jobId)}
    >
      <JobStatusBadge status={status} />
    </Button>
  );
}

function VersionShape({
  entity,
  version,
}: {
  entity: BusinessEntity;
  version: EntityVersion;
}) {
  const t = useTranslate();
  const attributes = draftsFromVersion(version);

  const configText = (attr: AttributeDraft): string | null => {
    if (attr.type === "reference") {
      return referenceSummaryLabel({
        targetEntityId: attr.target_entity_id,
        selfEntityId: entity.id,
        selfName: entity.name,
        selfTableName: entity.table_name,
        cachedName: attr.target_name,
        cachedTableName: attr.target_table_name,
        emptyNameLabel: t("entities.attributes.selfEntity"),
      });
    }
    const fact = attributeConfigSummary(attr);
    if (!fact) return null;
    if (fact.kind === "max_length") {
      return t("entities.attributes.config.maxLength", {
        label: t("entities.fields.maxLength"),
        value: fact.value,
      });
    }
    if (fact.kind === "decimal") {
      return t("entities.attributes.config.decimal", {
        precisionLabel: t("entities.fields.precision"),
        precision: fact.precision,
        scaleLabel: t("entities.fields.scale"),
        scale: fact.scale,
      });
    }
    return t("entities.attributes.config.enumeration", { count: fact.count });
  };

  const yesNo = (value: boolean) =>
    value ? t("form.value.yes") : t("form.value.no");

  return (
    <Stack gap="md">
      <Group gap="xl" align="flex-start">
        <DisplayField
          label={t("entities.fields.tableName")}
          value={
            <Text ff="monospace" size="sm">
              {version.table_name ?? "—"}
            </Text>
          }
        />
        <DisplayField
          label={t("entities.fields.versionStatus")}
          value={<PublishStatusBadge publishStatus={version.publish_status} />}
        />
      </Group>
      {attributes.length === 0 ? (
        <EmptyState />
      ) : (
        <Table.ScrollContainer minWidth={720}>
          <Table horizontalSpacing="sm" verticalSpacing="xs">
            <Table.Thead>
              <Table.Tr>
                <Table.Th>{t("entities.fields.attributeName")}</Table.Th>
                <Table.Th>{t("entities.fields.attributeType")}</Table.Th>
                <Table.Th>{t("entities.fields.attributeConfig")}</Table.Th>
                <Table.Th>{t("entities.fields.required")}</Table.Th>
                <Table.Th>{t("entities.fields.unique")}</Table.Th>
                <Table.Th>{t("entities.fields.indexed")}</Table.Th>
                <Table.Th>{t("entities.fields.attributeDescription")}</Table.Th>
              </Table.Tr>
            </Table.Thead>
            <Table.Tbody>
              {attributes.map((attr) => {
                const config = configText(attr);
                return (
                  <Table.Tr key={attr.name}>
                    <Table.Td>
                      <Text size="sm">{attr.name}</Text>
                    </Table.Td>
                    <Table.Td>
                      <Stack gap={2}>
                        <Text size="sm">
                          {t(`entities.attributeType.${attr.type}`)}
                        </Text>
                        <Text size="xs" c="dimmed" ff="monospace">
                          {physicalColumnType(attr)}
                        </Text>
                      </Stack>
                    </Table.Td>
                    <Table.Td>
                      {config ? <Text size="sm">{config}</Text> : null}
                    </Table.Td>
                    <Table.Td>
                      <Text size="sm">{yesNo(attr.required)}</Text>
                    </Table.Td>
                    <Table.Td>
                      <Text size="sm">{yesNo(attr.unique)}</Text>
                    </Table.Td>
                    <Table.Td>
                      <Text size="sm">{yesNo(attr.indexed)}</Text>
                    </Table.Td>
                    <Table.Td>
                      <Text size="sm">{attr.description}</Text>
                    </Table.Td>
                  </Table.Tr>
                );
              })}
            </Table.Tbody>
          </Table>
        </Table.ScrollContainer>
      )}
    </Stack>
  );
}
