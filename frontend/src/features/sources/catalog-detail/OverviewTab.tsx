"use client";

import {
  Badge,
  Button,
  Group,
  MultiSelect,
  NumberInput,
  Select,
  SimpleGrid,
  Stack,
  TagsInput,
  Text,
  TextInput,
  Textarea,
  Title,
} from "@mantine/core";
import { useForm } from "@mantine/form";
import { useNotification, useTranslate } from "@refinedev/core";
import { useEffect, useMemo, useState } from "react";

import { DisplayField } from "@/components/display/DisplayField";
import { patchObjectSemantics } from "@/features/sources/api";
import type {
  CatalogObject,
  ObjectCategory,
} from "@/features/sources/types";
import { ApiError } from "@/lib/api";

const OBJECT_CATEGORY_OPTIONS: { value: ObjectCategory; label: string }[] = [
  { value: "transaction_fact", label: "transaction_fact" },
  { value: "master_data", label: "master_data" },
  { value: "dimension", label: "dimension" },
  { value: "reference", label: "reference" },
  { value: "event", label: "event" },
];

type OverviewFormValues = {
  business_name: string;
  business_description: string;
  object_category: string | null;
  grain_description: string;
  business_domain: string;
  business_primary_key: string[];
  primary_time_field: string | null;
  time_role: string;
  primary_status_field: string | null;
  status_meaning: string;
  input_role_hint: string;
  main_upstream_or_dimension_objects: string[];
  likely_child_objects: string[];
  evidence_summary: string[];
  open_questions: string[];
  confidence: number | string;
};

type OverviewTabProps = {
  object: CatalogObject;
  writable: boolean;
  onSaved: (object: CatalogObject) => void;
};

function formFromObject(obj: CatalogObject): OverviewFormValues {
  return {
    business_name: obj.business_name ?? "",
    business_description: obj.business_description ?? "",
    object_category: obj.object_category ? String(obj.object_category) : null,
    grain_description: obj.grain_description ?? "",
    business_domain: obj.business_domain ?? "",
    business_primary_key: obj.business_primary_key ?? [],
    primary_time_field: obj.time_semantics?.primary_time_field ?? null,
    time_role: obj.time_semantics?.time_role ?? "",
    primary_status_field: obj.status_semantics?.primary_status_field ?? null,
    status_meaning: obj.status_semantics?.status_meaning ?? "",
    input_role_hint: obj.relation_summary?.input_role_hint ?? "",
    main_upstream_or_dimension_objects:
      obj.relation_summary?.main_upstream_or_dimension_objects ?? [],
    likely_child_objects: obj.relation_summary?.likely_child_objects ?? [],
    evidence_summary: obj.evidence_summary ?? [],
    open_questions: obj.open_questions ?? [],
    confidence: obj.confidence ?? "",
  };
}

export function OverviewTab({ object, writable, onSaved }: OverviewTabProps) {
  const t = useTranslate();
  const { open } = useNotification();
  const [saving, setSaving] = useState(false);
  const form = useForm<OverviewFormValues>({
    initialValues: formFromObject(object),
  });

  useEffect(() => {
    form.setValues(formFromObject(object));
    // eslint-disable-next-line react-hooks/exhaustive-deps -- reset when object identity/content changes
  }, [object.id, object.semantics_updated_at]);

  const columnOptions = useMemo(
    () => object.columns.map((c) => ({ value: c.name, label: c.name })),
    [object.columns],
  );

  const save = async (values: OverviewFormValues) => {
    setSaving(true);
    try {
      const confidenceRaw =
        values.confidence === "" || values.confidence === null
          ? null
          : Number(values.confidence);
      const data = await patchObjectSemantics(object.id, {
        business_name: values.business_name,
        business_description: values.business_description,
        object_category:
          (values.object_category as ObjectCategory | null) || null,
        grain_description: values.grain_description || null,
        business_domain: values.business_domain || null,
        business_primary_key: values.business_primary_key,
        time_semantics: {
          primary_time_field: values.primary_time_field,
          time_role: values.time_role || null,
        },
        status_semantics: {
          primary_status_field: values.primary_status_field,
          status_meaning: values.status_meaning || null,
        },
        relation_summary: {
          input_role_hint: values.input_role_hint || null,
          main_upstream_or_dimension_objects:
            values.main_upstream_or_dimension_objects,
          likely_child_objects: values.likely_child_objects,
        },
        evidence_summary: values.evidence_summary,
        open_questions: values.open_questions,
        confidence:
          confidenceRaw !== null && Number.isFinite(confidenceRaw)
            ? confidenceRaw
            : null,
      });
      onSaved(data.object);
      form.setValues(formFromObject(data.object));
      open?.({ type: "success", message: t("catalog.semantics.saved") });
    } catch (err) {
      open?.({
        type: "error",
        message: err instanceof ApiError ? err.detail : String(err),
      });
    } finally {
      setSaving(false);
    }
  };

  return (
    <SimpleGrid cols={{ base: 1, lg: 2 }} spacing="lg">
      <Stack>
        <TextInput
          label={t("catalog.semantics.businessName")}
          {...form.getInputProps("business_name")}
          disabled={!writable}
        />
        <Textarea
          label={t("catalog.semantics.businessDescription")}
          {...form.getInputProps("business_description")}
          disabled={!writable}
          minRows={3}
        />
        <Select
          label={t("catalog.semantics.category")}
          data={OBJECT_CATEGORY_OPTIONS}
          clearable
          searchable
          {...form.getInputProps("object_category")}
          disabled={!writable}
        />
        <Textarea
          label={t("catalog.semantics.grain")}
          {...form.getInputProps("grain_description")}
          disabled={!writable}
          minRows={2}
        />
        <TextInput
          label={t("catalog.semantics.domain")}
          {...form.getInputProps("business_domain")}
          disabled={!writable}
        />
        <MultiSelect
          label={t("catalog.semantics.businessPrimaryKey")}
          data={columnOptions}
          searchable
          {...form.getInputProps("business_primary_key")}
          disabled={!writable}
        />
        <Group grow align="flex-start">
          <Select
            label={t("catalog.semantics.timeField")}
            data={columnOptions}
            clearable
            searchable
            {...form.getInputProps("primary_time_field")}
            disabled={!writable}
          />
          <TextInput
            label={t("catalog.semantics.timeRole")}
            {...form.getInputProps("time_role")}
            disabled={!writable}
          />
        </Group>
        <Group grow align="flex-start">
          <Select
            label={t("catalog.semantics.statusField")}
            data={columnOptions}
            clearable
            searchable
            {...form.getInputProps("primary_status_field")}
            disabled={!writable}
          />
          <TextInput
            label={t("catalog.semantics.statusMeaning")}
            {...form.getInputProps("status_meaning")}
            disabled={!writable}
          />
        </Group>
        <TextInput
          label={t("catalog.semantics.inputRoleHint")}
          {...form.getInputProps("input_role_hint")}
          disabled={!writable}
        />
        <TagsInput
          label={t("catalog.semantics.upstreamObjects")}
          {...form.getInputProps("main_upstream_or_dimension_objects")}
          disabled={!writable}
        />
        <TagsInput
          label={t("catalog.semantics.childObjects")}
          {...form.getInputProps("likely_child_objects")}
          disabled={!writable}
        />
        <TagsInput
          label={t("catalog.semantics.evidenceSummary")}
          {...form.getInputProps("evidence_summary")}
          disabled={!writable}
        />
        <TagsInput
          label={t("catalog.semantics.openQuestions")}
          {...form.getInputProps("open_questions")}
          disabled={!writable}
        />
        <NumberInput
          label={t("catalog.semantics.confidence")}
          {...form.getInputProps("confidence")}
          min={0}
          max={1}
          step={0.1}
          decimalScale={2}
          allowDecimal
          clampBehavior="strict"
          disabled={!writable}
        />
        {writable ? (
          <Button
            size="sm"
            loading={saving}
            onClick={() => void save(form.values)}
            w="fit-content"
          >
            {t("catalog.semantics.saveObject")}
          </Button>
        ) : null}
      </Stack>

      <Stack gap="md">
        <Title order={5}>{t("catalog.structure.title")}</Title>
        <DisplayField
          label={t("catalog.structure.comment")}
          value={object.comment}
        />
        <DisplayField
          label={t("catalog.structure.primaryKey")}
          value={
            object.primary_key?.length
              ? object.primary_key.join(", ")
              : null
          }
          fallback={t("catalog.structure.none")}
        />
        <DisplayField
          label={t("catalog.structure.foreignKeys")}
          value={
            object.foreign_keys?.length ? (
              <Stack gap={4}>
                {object.foreign_keys.map((fk) => (
                  <Text key={fk.name} size="sm">
                    {fk.name}: {fk.columns.join(", ")} → {fk.ref_schema}.
                    {fk.ref_table}({fk.ref_columns.join(", ")})
                    {!fk.is_present ? (
                      <Badge size="xs" ml="xs" color="gray">
                        {t("catalog.fields.absentValue")}
                      </Badge>
                    ) : null}
                  </Text>
                ))}
              </Stack>
            ) : null
          }
          fallback={t("catalog.structure.none")}
        />
        <DisplayField
          label={t("catalog.structure.indexes")}
          value={
            object.indexes?.length ? (
              <Stack gap={4}>
                {object.indexes.map((idx) => (
                  <Text key={idx.name} size="sm">
                    {idx.name}: {idx.columns.join(", ")}
                    {idx.is_unique ? (
                      <Badge size="xs" ml="xs">
                        {t("catalog.structure.unique")}
                      </Badge>
                    ) : null}
                  </Text>
                ))}
              </Stack>
            ) : null
          }
          fallback={t("catalog.structure.none")}
        />
        <DisplayField
          label={t("catalog.structure.collectedAt")}
          value={object.collected_at}
        />
      </Stack>
    </SimpleGrid>
  );
}
