"use client";

import {
  Badge,
  Button,
  Group,
  MultiSelect,
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
import { listBusinessDomains } from "@/features/business-domains/api";
import type { BusinessDomain } from "@/features/business-domains/types";
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
  business_domain_code: string | null;
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
    business_domain_code: obj.business_domain?.code ?? null,
    business_primary_key: obj.business_primary_key ?? [],
    evidence_summary: obj.evidence_summary ?? [],
    open_questions: obj.open_questions ?? [],
  };
}

export function OverviewTab({ object, writable, onSaved }: OverviewTabProps) {
  const t = useTranslate();
  const { open } = useNotification();
  const [saving, setSaving] = useState(false);
  const [domains, setDomains] = useState<BusinessDomain[]>([]);
  const form = useForm<OverviewFormValues>({
    initialValues: formFromObject(object),
  });

  useEffect(() => {
    form.setValues(formFromObject(object));
    // eslint-disable-next-line react-hooks/exhaustive-deps -- reset when object identity/content changes
  }, [object.id, object.semantics_updated_at]);

  useEffect(() => {
    void listBusinessDomains({ limit: 500 })
      .then((data) => setDomains(data.items))
      .catch(() => setDomains([]));
  }, []);

  const columnOptions = useMemo(
    () => object.columns.map((c) => ({ value: c.name, label: c.name })),
    [object.columns],
  );

  const domainOptions = useMemo(
    () =>
      domains.map((d) => ({
        value: d.code,
        label: `${d.name} (${d.code})`,
      })),
    [domains],
  );

  const save = async (values: OverviewFormValues) => {
    setSaving(true);
    try {
      const data = await patchObjectSemantics(object.id, {
        business_name: values.business_name,
        business_description: values.business_description,
        object_category:
          (values.object_category as ObjectCategory | null) || null,
        grain_description: values.grain_description || null,
        business_domain_code: values.business_domain_code || null,
        business_primary_key: values.business_primary_key,
        evidence_summary: values.evidence_summary,
        open_questions: values.open_questions,
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
        <Select
          label={t("catalog.semantics.domain")}
          data={domainOptions}
          clearable
          searchable
          {...form.getInputProps("business_domain_code")}
          disabled={!writable}
        />
        <MultiSelect
          label={t("catalog.semantics.businessPrimaryKey")}
          data={columnOptions}
          searchable
          {...form.getInputProps("business_primary_key")}
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
          value={object.collected_at}
        />
      </Stack>
    </SimpleGrid>
  );
}
