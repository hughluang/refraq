"use client";

import {
  Badge,
  Button,
  Group,
  SimpleGrid,
  Stack,
  Text,
  Title,
} from "@mantine/core";
import { useTranslate } from "@refinedev/core";
import { useEffect, useMemo, useState } from "react";

import { DisplayField } from "@/components/display/DisplayField";
import { Instant } from "@/components/display/Instant";
import { MultiSelectField } from "@/components/form/MultiSelectField";
import {
  FormErrorSummary,
  saveFailureFrom,
  type SaveFailure,
} from "@/components/form/FormErrorSummary";
import { useConsoleForm } from "@/components/form/useConsoleForm";
import { RecordPicker } from "@/components/form/RecordPicker";
import { businessDomainRecordAdapter } from "@/components/form/recordPickerAdapters";
import { SelectField } from "@/components/form/SelectField";
import { TagsField } from "@/components/form/TagsField";
import { TextareaField } from "@/components/form/TextareaField";
import { TextField } from "@/components/form/TextField";
import { getBusinessDomain } from "@/features/business-domains/api";
import { patchObjectSemantics } from "@/features/sources/api/semantics";
import { useSemanticsSave } from "@/features/sources/catalog-detail/useSemanticsSave";
import type {
  CatalogObject,
  ObjectCategory,
} from "@/features/sources/types";

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
  business_domain_id: string | null;
  business_primary_key: string[];
  evidence_summary: string[];
  open_questions: string[];
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
    business_domain_id: obj.business_domain?.id ?? null,
    business_primary_key: obj.business_primary_key ?? [],
    evidence_summary: obj.evidence_summary ?? [],
    open_questions: obj.open_questions ?? [],
  };
}

export function OverviewTab({ object, writable, onSaved }: OverviewTabProps) {
  const t = useTranslate();
  const [saveFailure, setSaveFailure] = useState<SaveFailure | null>(null);
  const form = useConsoleForm<OverviewFormValues>({
    initialValues: formFromObject(object),
    onValuesChange: () => setSaveFailure(null),
  });
  const { save: saveSemantics } = useSemanticsSave(onSaved, {
    onError: (error) => {
      setSaveFailure(
        saveFailureFrom(t, error, form.applyApiError(error), t("common.error")),
      );
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

  const save = async (values: OverviewFormValues) => {
    const saved = await saveSemantics(async () => {
      const business_domain_code = values.business_domain_id
        ? (await getBusinessDomain(values.business_domain_id)).domain.code
        : null;
      return patchObjectSemantics(object.id, {
        business_name: values.business_name,
        business_description: values.business_description,
        object_category:
          (values.object_category as ObjectCategory | null) || null,
        grain_description: values.grain_description || null,
        business_domain_code,
        business_primary_key: values.business_primary_key,
        evidence_summary: values.evidence_summary,
        open_questions: values.open_questions,
      });
    });
    if (saved) {
      form.setValues(formFromObject(saved));
      form.markSaved();
      setSaveFailure(null);
    }
  };

  return (
    <SimpleGrid cols={{ base: 1, lg: 2 }} spacing="lg">
      <form onSubmit={form.onSubmit((values) => save(values))}>
      <Stack>
        <FormErrorSummary failure={saveFailure} />
        <TextField
          label={t("catalog.semantics.businessName")}
          editable={writable}
          {...form.fieldProps("business_name")}
        />
        <TextareaField
          label={t("catalog.semantics.businessDescription")}
          editable={writable}
          minRows={3}
          {...form.fieldProps("business_description")}
        />
        <SelectField
          label={t("catalog.semantics.category")}
          data={OBJECT_CATEGORY_OPTIONS}
          clearable
          searchable
          editable={writable}
          {...form.fieldProps("object_category")}
        />
        <TextareaField
          label={t("catalog.semantics.grain")}
          editable={writable}
          minRows={2}
          {...form.fieldProps("grain_description")}
        />
        <RecordPicker
          label={t("catalog.semantics.domain")}
          editable={writable}
          clearable
          adapter={businessDomainRecordAdapter()}
          known={
            object.business_domain
              ? [
                  {
                    id: object.business_domain.id,
                    name: object.business_domain.name,
                    key: object.business_domain.code,
                  },
                ]
              : undefined
          }
          {...form.fieldProps("business_domain_id")}
        />
        <MultiSelectField
          label={t("catalog.semantics.businessPrimaryKey")}
          data={columnOptions}
          searchable
          editable={writable}
          {...form.fieldProps("business_primary_key")}
        />
        <TagsField
          label={t("catalog.semantics.evidenceSummary")}
          editable={writable}
          {...form.fieldProps("evidence_summary")}
        />
        <TagsField
          label={t("catalog.semantics.openQuestions")}
          editable={writable}
          {...form.fieldProps("open_questions")}
        />
        {writable ? (
          <Button
            type="submit"
            size="sm"
            loading={form.submitting}
            w="fit-content"
          >
            {t("catalog.semantics.saveObject")}
          </Button>
        ) : null}
      </Stack>
      </form>

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
                  <Group key={fk.name} gap="xs" wrap="wrap">
                    <Text size="sm">
                      {fk.name}: {fk.columns.join(", ")} → {fk.ref_schema}.
                      {fk.ref_table}({fk.ref_columns.join(", ")})
                    </Text>
                    {!fk.is_present ? (
                      <Badge size="xs" color="gray">
                        {t("catalog.fields.absentValue")}
                      </Badge>
                    ) : null}
                  </Group>
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
                  <Group key={idx.name} gap="xs" wrap="wrap">
                    <Text size="sm">
                      {idx.name}: {idx.columns.join(", ")}
                    </Text>
                    {idx.is_unique ? (
                      <Badge size="xs">
                        {t("catalog.structure.unique")}
                      </Badge>
                    ) : null}
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
      </Stack>
    </SimpleGrid>
  );
}
