"use client";

import {
  ActionIcon,
  Anchor,
  Badge,
  Button,
  Card,
  Code,
  Group,
  Paper,
  Progress,
  SimpleGrid,
  Stack,
  Text,
  Tooltip,
} from "@mantine/core";
import { useNotification, useTranslate } from "@refinedev/core";
import { useEffect, useMemo, type ReactNode } from "react";

import { DisplayField } from "@/components/display/DisplayField";
import { Instant } from "@/components/display/Instant";
import { StatusBadge } from "@/components/display/StatusBadge";
import { Callout } from "@/components/feedback/Callout";
import { presentSaveFailure } from "@/components/feedback/presentSaveFailure";
import { FormSection } from "@/components/form/FormSection";
import { MultiSelectField } from "@/components/form/MultiSelectField";
import { SelectField } from "@/components/form/SelectField";
import { TagsField } from "@/components/form/TagsField";
import { TextField } from "@/components/form/TextField";
import { TextareaField } from "@/components/form/TextareaField";
import { useConsoleForm } from "@/components/form/useConsoleForm";
import {
  CheckIcon,
  CircleDashedIcon,
  CopyIcon,
  KeyIcon,
} from "@/components/icons";
import { SectionHeader } from "@/components/layout/SectionHeader";
import { ConsoleLink } from "@/components/navigation/ConsoleLink";
import { patchObjectSemantics } from "@/features/sources/api/semantics";
import { formatBytes } from "@/features/sources/catalog-detail/formatBytes";
import { useSemanticsSave } from "@/features/sources/catalog-detail/useSemanticsSave";
import {
  objectCategoryLabel,
  semanticSourceLabel,
} from "@/features/sources/catalogLabel";
import type {
  CatalogColumn,
  CatalogObject,
  ObjectCategory,
} from "@/features/sources/types";
import { copyText } from "@/lib/copy-text";

const OBJECT_CATEGORIES: readonly ObjectCategory[] = [
  "transaction_fact",
  "master_data",
  "dimension",
  "reference",
  "event",
];

type OverviewFormValues = {
  business_name: string;
  business_description: string;
  object_category: string | null;
  grain_description: string;
  business_primary_key: string[];
  evidence_summary: string[];
  open_questions: string[];
};

type OverviewTabProps = {
  object: CatalogObject;
  writable: boolean;
  onSaved: (object: CatalogObject) => void;
  onOpenColumn?: (columnId: string, filter?: "all" | "empty") => void;
  onOpenTab?: (tab: string) => void;
  onOpenColumnsCoverage?: (filter: "all" | "empty") => void;
  mirrorControls?: ReactNode;
};

function isColumnDocumented(col: CatalogColumn): boolean {
  return Boolean(
    col.business_name?.trim() ||
      col.business_description?.trim() ||
      col.column_semantics?.semantic_type?.trim() ||
      (col.enum_catalog?.length ?? 0) > 0,
  );
}

function parseLocatorSource(locatorKey: string): {
  engine: string | null;
  sourceKey: string | null;
} {
  const parts = locatorKey.split("/");
  if (parts[0] === "obj" && parts.length >= 3) {
    return {
      engine: parts[1] || null,
      sourceKey: parts[2] || null,
    };
  }
  return { engine: null, sourceKey: null };
}

function formFromObject(obj: CatalogObject): OverviewFormValues {
  return {
    business_name: obj.business_name ?? "",
    business_description: obj.business_description ?? "",
    object_category: obj.object_category ? String(obj.object_category) : null,
    grain_description: obj.grain_description ?? "",
    business_primary_key: obj.business_primary_key ?? [],
    evidence_summary: obj.evidence_summary ?? [],
    open_questions: obj.open_questions ?? [],
  };
}

export function OverviewTab({
  object,
  writable,
  onSaved,
  onOpenColumn,
  onOpenTab,
  onOpenColumnsCoverage,
  mirrorControls,
}: OverviewTabProps) {
  const t = useTranslate();
  const { open } = useNotification();
  const form = useConsoleForm<OverviewFormValues>({
    initialValues: formFromObject(object),
  });
  const { save: saveSemantics } = useSemanticsSave(onSaved, {
    onError: (error) => {
      presentSaveFailure(t, error, form.applyApiError);
    },
  });

  useEffect(() => {
    form.setValues(formFromObject(object));
    form.markSaved();
    // eslint-disable-next-line react-hooks/exhaustive-deps -- reset when object identity/content changes
  }, [object.id, object.semantics_updated_at]);

  const columnOptions = useMemo(
    () => object.columns.map((c) => ({ value: c.name, label: c.name })),
    [object.columns],
  );

  const categoryOptions = useMemo(
    () =>
      OBJECT_CATEGORIES.map((category) => ({
        value: category,
        label: objectCategoryLabel(t, category),
      })),
    [t],
  );

  const save = async (values: OverviewFormValues) => {
    const saved = await saveSemantics(async () => {
      return patchObjectSemantics(object.id, {
        business_name: values.business_name,
        business_description: values.business_description,
        object_category:
          (values.object_category as ObjectCategory | null) || null,
        grain_description: values.grain_description || null,
        business_primary_key: values.business_primary_key,
        evidence_summary: values.evidence_summary,
        open_questions: values.open_questions,
      });
    });
    if (saved) {
      form.setValues(formFromObject(saved));
      form.markSaved();
    }
  };

  const openQuestionsCount = object.open_questions?.length ?? 0;
  const isRoutine =
    object.object_type === "procedure" || object.object_type === "function";

  const hasBusinessName = Boolean(form.values.business_name.trim());
  const hasBusinessDescription = Boolean(
    form.values.business_description.trim(),
  );
  const hasNoOpenQuestions = form.values.open_questions.length === 0;

  const categoryHint = form.values.object_category
    ? t(`catalog.overview.categoryHint.${form.values.object_category}`)
    : undefined;

  const uniqueIndexes = (object.indexes ?? []).filter((idx) => idx.is_unique);
  const secondaryIndexes = (object.indexes ?? []).filter(
    (idx) => !idx.is_unique,
  );

  const hasColumns =
    (object.object_type !== "procedure" && object.object_type !== "function") ||
    object.columns.length > 0;
  const documentedCount = object.columns.filter(isColumnDocumented).length;
  const { engine: locatorEngine, sourceKey: locatorSourceKey } =
    parseLocatorSource(object.locator_key);
  const sourceEngine = object.source?.engine ?? locatorEngine;
  const sourceLabel =
    object.source?.name ??
    object.source?.key ??
    locatorSourceKey ??
    object.source_id;

  const copyLocator = async () => {
    try {
      await copyText(object.locator_key);
      open?.({ type: "success", message: t("common.copy.success") });
    } catch {
      open?.({
        type: "error",
        message: t("common.copy.failed"),
      });
    }
  };

  return (
    <Stack gap="md">
      {openQuestionsCount > 0 ? (
        <Callout tone="notice">
          {t("catalog.overview.openQuestionsCallout", {
            count: openQuestionsCount,
          })}
        </Callout>
      ) : null}

      {isRoutine ? (
        <Callout tone="info">
          <Group justify="space-between" align="center" gap="sm" wrap="wrap">
            <Text size="sm">{t("catalog.overview.routineCallout")}</Text>
            {object.ddl && onOpenTab ? (
              <Button
                type="button"
                variant="subtle"
                size="xs"
                onClick={() => onOpenTab("ddl")}
              >
                {t("catalog.overview.openDdl")}
              </Button>
            ) : null}
          </Group>
        </Callout>
      ) : null}

      <SimpleGrid cols={{ base: 1, lg: 2 }} spacing="md" style={{ alignItems: "start" }}>
        <Card withBorder padding="lg">
          <Stack gap="md">
            <Paper
              withBorder
              px="md"
              py="xs"
              radius="md"
              role="region"
              aria-label={t("catalog.detail.telemetryAria")}
            >
              <Group gap="lg" wrap="wrap" align="center">
                <Group gap="xs" wrap="nowrap">
                  <Text size="xs" c="dimmed">
                    {t("catalog.detail.source")}:
                  </Text>
                  {sourceEngine ? (
                    <Badge variant="light" size="xs" tt="uppercase">
                      {sourceEngine}
                    </Badge>
                  ) : null}
                  <Anchor
                    component={ConsoleLink}
                    href={`/console/sources/${encodeURIComponent(object.source_id)}`}
                    size="xs"
                    fw={500}
                  >
                    {sourceLabel}
                  </Anchor>
                  <Anchor
                    component={ConsoleLink}
                    href={`/console/sources/${encodeURIComponent(object.source_id)}?tab=diffs`}
                    size="xs"
                    c="dimmed"
                  >
                    {t("catalog.detail.structureDiffs")}
                  </Anchor>
                </Group>

                <Group gap={6} wrap="nowrap">
                  <Text size="xs" c="dimmed">
                    {t("catalog.detail.locator")}:
                  </Text>
                  <Code fz="xs">{object.locator_key}</Code>
                  <Tooltip label={t("catalog.copyLocator")}>
                    <ActionIcon
                      variant="subtle"
                      size="sm"
                      aria-label={t("catalog.copyLocator")}
                      onClick={() => void copyLocator()}
                    >
                      <CopyIcon size={14} />
                    </ActionIcon>
                  </Tooltip>
                </Group>

                {hasColumns && object.columns.length > 0 ? (
                  <Button
                    type="button"
                    variant="subtle"
                    size="compact-xs"
                    title={t("catalog.detail.columnsCoverageHint")}
                    onClick={() => {
                      const filter =
                        documentedCount < object.columns.length
                          ? "empty"
                          : "all";
                      if (onOpenColumnsCoverage) {
                        onOpenColumnsCoverage(filter);
                      } else {
                        onOpenTab?.("columns");
                      }
                    }}
                  >
                    <Group gap={6} wrap="nowrap">
                      <Progress
                        value={(documentedCount / object.columns.length) * 100}
                        w={56}
                        size="sm"
                        aria-hidden="true"
                      />
                      <Text size="xs">
                        {t("catalog.detail.columnsCoverage", {
                          documented: documentedCount,
                          total: object.columns.length,
                        })}
                      </Text>
                    </Group>
                  </Button>
                ) : null}

                {openQuestionsCount > 0 ? (
                  <Badge variant="light" color="yellow" size="sm">
                    {t("catalog.detail.openQuestionsBadge", {
                      count: openQuestionsCount,
                    })}
                  </Badge>
                ) : null}

                {object.estimated_rows != null ? (
                  <Text size="xs" c="dimmed">
                    {t("catalog.detail.estimatedRows")}:{" "}
                    <Text component="span" c="var(--mantine-color-text)" fw={500}>
                      {object.estimated_rows.toLocaleString()}
                    </Text>
                  </Text>
                ) : null}

                {object.source_size_bytes != null ? (
                  <Text size="xs" c="dimmed">
                    {t("catalog.detail.storageSize")}:{" "}
                    <Text component="span" c="var(--mantine-color-text)" fw={500}>
                      {formatBytes(object.source_size_bytes)}
                    </Text>
                  </Text>
                ) : null}

                {object.collected_at ? (
                  <Text size="xs" c="dimmed">
                    {t("catalog.structure.collectedAt")}:{" "}
                    <Instant value={object.collected_at} />
                  </Text>
                ) : null}

                {object.semantics_updated_at ? (
                  <Group gap="xs" wrap="nowrap">
                    <Text size="xs" c="dimmed">
                      {t("catalog.semantics.updatedAt")}:{" "}
                      <Instant value={object.semantics_updated_at} />
                    </Text>
                    {object.semantic_source ? (
                      <Badge variant="default" size="xs">
                        {semanticSourceLabel(t, object.semantic_source)}
                      </Badge>
                    ) : null}
                  </Group>
                ) : null}
              </Group>
            </Paper>

            <form onSubmit={form.onSubmit((values) => save(values))}>
            <Stack gap="md">
              <Paper withBorder p="xs" radius="sm">
                <Stack gap={6}>
                  <Text size="xs" fw={600} c="dimmed">
                    {t("catalog.overview.readinessTitle")}
                  </Text>
                  <Group gap="xs" wrap="wrap">
                    <Badge
                      variant="light"
                      color={hasBusinessName ? "green" : "gray"}
                      size="sm"
                      leftSection={
                        hasBusinessName ? (
                          <CheckIcon size={12} />
                        ) : (
                          <CircleDashedIcon size={12} />
                        )
                      }
                    >
                      {t("catalog.overview.checkBusinessName")}
                    </Badge>
                    <Badge
                      variant="light"
                      color={hasBusinessDescription ? "green" : "gray"}
                      size="sm"
                      leftSection={
                        hasBusinessDescription ? (
                          <CheckIcon size={12} />
                        ) : (
                          <CircleDashedIcon size={12} />
                        )
                      }
                    >
                      {t("catalog.overview.checkBusinessDescription")}
                    </Badge>
                    <Badge
                      variant="light"
                      color={hasNoOpenQuestions ? "green" : "gray"}
                      size="sm"
                      leftSection={
                        hasNoOpenQuestions ? (
                          <CheckIcon size={12} />
                        ) : (
                          <CircleDashedIcon size={12} />
                        )
                      }
                    >
                      {t("catalog.overview.checkNoOpenQuestions")}
                    </Badge>
                  </Group>
                </Stack>
              </Paper>

              <FormSection
                title={t("catalog.overview.sectionIdentity")}
                description={t("catalog.overview.sectionIdentityDesc")}
                columns={1}
                order={3}
              >
                <TextField
                  label={t("catalog.semantics.businessName")}
                  editable={writable}
                  {...form.fieldProps("business_name")}
                />
                <Stack gap={4}>
                  <TextareaField
                    label={t("catalog.semantics.businessDescription")}
                    editable={writable}
                    minRows={3}
                    {...form.fieldProps("business_description")}
                  />
                  {writable &&
                  object.comment &&
                  !form.values.business_description.trim() ? (
                    <Button
                      type="button"
                      variant="subtle"
                      size="xs"
                      w="fit-content"
                      onClick={() =>
                        form.setFieldValue(
                          "business_description",
                          object.comment ?? "",
                        )
                      }
                    >
                      {t("catalog.overview.useDbComment")}
                    </Button>
                  ) : null}
                </Stack>
                <SelectField
                  label={t("catalog.semantics.category")}
                  description={categoryHint}
                  data={categoryOptions}
                  clearable
                  searchable
                  editable={writable}
                  {...form.fieldProps("object_category")}
                />
              </FormSection>

              <FormSection
                title={t("catalog.overview.sectionGrain")}
                description={t("catalog.overview.sectionGrainDesc")}
                columns={1}
                order={3}
              >
                <TextareaField
                  label={t("catalog.semantics.grain")}
                  editable={writable}
                  minRows={2}
                  {...form.fieldProps("grain_description")}
                />
                <Stack gap={4}>
                  <MultiSelectField
                    label={t("catalog.semantics.businessPrimaryKey")}
                    data={columnOptions}
                    searchable
                    editable={writable}
                    {...form.fieldProps("business_primary_key")}
                  />
                  {writable && (object.primary_key?.length ?? 0) > 0 ? (
                    <Button
                      type="button"
                      variant="subtle"
                      size="xs"
                      w="fit-content"
                      onClick={() =>
                        form.setFieldValue("business_primary_key", [
                          ...(object.primary_key ?? []),
                        ])
                      }
                    >
                      {t("catalog.overview.usePhysicalPk")}
                    </Button>
                  ) : null}
                </Stack>
              </FormSection>

              <FormSection
                title={t("catalog.overview.sectionEvidence")}
                description={t("catalog.overview.sectionEvidenceDesc")}
                columns={1}
                order={3}
              >
                <TagsField
                  label={t("catalog.semantics.evidenceSummary")}
                  editable={writable}
                  splitChars={["\n"]}
                  {...form.fieldProps("evidence_summary")}
                />
                <TagsField
                  label={t("catalog.semantics.openQuestions")}
                  editable={writable}
                  splitChars={["\n"]}
                  {...form.fieldProps("open_questions")}
                />
              </FormSection>

              {writable ? (
                <Group gap="sm">
                  <Button
                    type="submit"
                    size="sm"
                    loading={form.submitting}
                    w="fit-content"
                  >
                    {t("catalog.semantics.saveObject")}
                  </Button>
                  {form.isDirty() ? (
                    <Button
                      type="button"
                      variant="subtle"
                      size="sm"
                      disabled={form.submitting}
                      onClick={() => form.reset()}
                    >
                      {t("catalog.overview.resetDraft")}
                    </Button>
                  ) : null}
                </Group>
              ) : null}
            </Stack>
          </form>
          </Stack>
        </Card>

        <Card withBorder padding="lg">
          <Stack gap="md">
            <SectionHeader title={t("catalog.structure.title")} order={2} />
            <DisplayField
              label={t("catalog.structure.comment")}
              value={object.comment}
            />
            <DisplayField
              label={t("catalog.structure.primaryKey")}
              value={
                object.primary_key?.length ? (
                  <Group gap="xs" wrap="wrap">
                    {object.primary_key.map((colName) => {
                      const col = object.columns.find(
                        (c) => c.name === colName,
                      );
                      if (onOpenColumn && col) {
                        return (
                          <Button
                            key={colName}
                            type="button"
                            variant="light"
                            size="compact-xs"
                            leftSection={<KeyIcon size={12} />}
                            aria-label={t("catalog.overview.inspectColumn", {
                              name: colName,
                            })}
                            onClick={() => onOpenColumn(col.id)}
                          >
                            <Code fz="xs">{colName}</Code>
                          </Button>
                        );
                      }
                      return (
                        <Badge
                          key={colName}
                          variant="light"
                          size="sm"
                          leftSection={<KeyIcon size={12} />}
                        >
                          {colName}
                        </Badge>
                      );
                    })}
                  </Group>
                ) : null
              }
              fallback={t("catalog.structure.none")}
            />
            <DisplayField
              label={t("catalog.structure.foreignKeys")}
              value={
                object.foreign_keys?.length ? (
                  <Stack gap={6}>
                    {object.foreign_keys.map((fk) => {
                      const targetName = `${fk.ref_schema}.${fk.ref_table}`;
                      return (
                        <Group key={fk.name} gap="xs" wrap="wrap" align="center">
                          <Code fz="xs">{fk.name}</Code>
                          <Text size="sm">
                            ({fk.columns.join(", ")}) →{" "}
                            {fk.ref_object_id ? (
                              <ConsoleLink
                                href={`/console/catalog/${encodeURIComponent(fk.ref_object_id)}`}
                                aria-label={t(
                                  "catalog.overview.openRefObject",
                                  { target: targetName },
                                )}
                              >
                                {targetName}
                              </ConsoleLink>
                            ) : (
                              targetName
                            )}{" "}
                            ({fk.ref_columns.join(", ")})
                          </Text>
                          {!fk.is_present ? (
                            <StatusBadge
                              tone="neutral"
                              labelKey="catalog.overview.fkRemoved"
                              size="xs"
                            />
                          ) : null}
                        </Group>
                      );
                    })}
                  </Stack>
                ) : null
              }
              fallback={t("catalog.structure.none")}
            />
            <DisplayField
              label={t("catalog.overview.uniqueConstraints")}
              value={
                uniqueIndexes.length ? (
                  <Stack gap={4}>
                    {uniqueIndexes.map((idx) => (
                      <Group key={idx.name} gap="xs" wrap="wrap">
                        <Code fz="xs">{idx.name}</Code>
                        <Text size="sm">({idx.columns.join(", ")})</Text>
                      </Group>
                    ))}
                  </Stack>
                ) : null
              }
              fallback={t("catalog.structure.none")}
            />
            <DisplayField
              label={t("catalog.overview.nonUniqueIndexes")}
              value={
                secondaryIndexes.length ? (
                  <Stack gap={4}>
                    {secondaryIndexes.map((idx) => (
                      <Group key={idx.name} gap="xs" wrap="wrap">
                        <Code fz="xs">{idx.name}</Code>
                        <Text size="sm">({idx.columns.join(", ")})</Text>
                      </Group>
                    ))}
                  </Stack>
                ) : null
              }
              fallback={t("catalog.structure.none")}
            />
            <DisplayField
              label={t("catalog.structure.collectedAt")}
              value={<Instant value={object.collected_at} />}
            />
            {mirrorControls}
          </Stack>
        </Card>
      </SimpleGrid>
    </Stack>
  );
}
