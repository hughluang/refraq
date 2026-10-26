"use client";

import { Badge, Drawer, Group, Stack, Table, Text } from "@mantine/core";
import { useTranslate } from "@refinedev/core";
import { useState } from "react";

import { DisplayField } from "@/components/display/DisplayField";
import { ListTable } from "@/components/display/ListTable";
import { RowActions, type RowActionVerb } from "@/components/display/RowActions";
import { EmptyState } from "@/components/feedback/EmptyState";
import { localListSession } from "@/lib/list-state";
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
import { JobReference } from "@/components/display/JobReference";
import { showContractInstant } from "@/lib/datetime";

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

function isMetadataHead(versions: EntityVersion[], version: EntityVersion): boolean {
  let head: EntityVersion | null = null;
  for (const item of versions) {
    if (item.publish_status !== "published") {
      continue;
    }
    if (head === null || item.version > head.version) {
      head = item;
    }
  }
  return head !== null && head.id === version.id;
}

function canDropVersion(
  entity: BusinessEntity,
  version: EntityVersion,
  versions: EntityVersion[],
): boolean {
  if (!version.alignment.table_present || !version.table_name) {
    return false;
  }
  if (entity.deprecated_at) {
    return true;
  }
  return !isMetadataHead(versions, version);
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

  const list = localListSession({ total: versions.length });

  return (
    <>
      <ListTable
        embedded
        list={list}
        columnCount={7}
        minWidth={960}
        emptyMessage={t("entities.versions.empty")}
        head={
          <Table.Tr>
            <Table.Th>{t("entities.fields.version")}</Table.Th>
            <Table.Th>{t("entities.fields.tableName")}</Table.Th>
            <Table.Th>{t("entities.fields.versionStatus")}</Table.Th>
            <Table.Th>{t("entities.fields.attributeCount")}</Table.Th>
            <Table.Th>{t("entities.fields.createdAt")}</Table.Th>
            <Table.Th>{t("entities.fields.publishJob")}</Table.Th>
            <Table.Th />
          </Table.Tr>
        }
      >
        {versions.map((version) => {
          const verbs: RowActionVerb[] = [
            {
              key: "view",
              label: t("entities.versions.view"),
              onClick: () => void view(version),
              safety: "immediate",
              disabledReason: viewingId === version.id ? t("common.loading") : undefined,
            },
          ];
          if (canDropTable && canDropVersion(entity, version, versions)) {
            verbs.push({
              key: "drop",
              label: t("entities.drop"),
              color: "red",
              onClick: () => onDrop(version),
              safety: "confirm",
              disabledReason: busy ? t("common.loading") : undefined,
            });
          }
          return (
            <Table.Tr key={version.id}>
              <Table.Td>
                <Group gap="xs" wrap="nowrap">
                  <Text size="sm">{version.version}</Text>
                  {isMetadataHead(versions, version) && !entity.deprecated_at ? (
                    <Badge variant="light" color="green" tt="none">
                      {t("entities.versions.serving")}
                    </Badge>
                  ) : null}
                </Group>
              </Table.Td>
              <Table.Td>
                <Text ff="monospace" size="sm">
                  {version.table_name ?? "—"}
                </Text>
              </Table.Td>
              <Table.Td>
                <PublishStatusBadge publishStatus={version.publish_status} />
              </Table.Td>
              <Table.Td>{version.attribute_count}</Table.Td>
              <Table.Td>
                {showContractInstant(version.created_at, formatInstant, t)}
              </Table.Td>
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
                <RowActions recordName={String(version.version)} verbs={verbs} />
              </Table.Td>
            </Table.Tr>
          );
        })}
      </ListTable>
      <Drawer
        opened={opened != null}
        onClose={() => setOpened(null)}
        position="right"
        size="xl"
        title={opened ? String(opened.version) : ""}
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
    <JobReference
      jobId={jobId}
      kind="entity_reconcile"
      status={status}
      onOpen={onOpenJob}
    />
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
    return fact.label;
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
                <Table.Th>{t("entities.fields.businessKey")}</Table.Th>
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
                      {attr.behind ? (
                        <Text size="xs" c="orange">
                          {t("entities.attributes.behind")}
                        </Text>
                      ) : null}
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
                      <Text size="sm">{yesNo(attr.business_key)}</Text>
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
