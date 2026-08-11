"use client";

import {
  ActionIcon,
  Badge,
  Button,
  Group,
  Stack,
  Tabs,
  Text,
  Tooltip,
} from "@mantine/core";
import { useCan, useNotification, useTranslate } from "@refinedev/core";
import Link from "next/link";
import { useCallback, useEffect, useMemo, useState } from "react";

import { PageError } from "@/components/feedback/PageError";
import { PageLoader } from "@/components/feedback/PageLoader";
import { PageChrome } from "@/components/layout/PageChrome";
import { ModuleAction, ModuleId } from "@/features/console/module-identity";
import {
  getCatalogObject,
  listObjectJoins,
  listSources,
} from "@/features/sources/api";
import { ColumnsTab } from "@/features/sources/catalog-detail/ColumnsTab";
import { DdlTab } from "@/features/sources/catalog-detail/DdlTab";
import { JoinsTab } from "@/features/sources/catalog-detail/JoinsTab";
import { OverviewTab } from "@/features/sources/catalog-detail/OverviewTab";
import { SampleTab } from "@/features/sources/catalog-detail/SampleTab";
import type {
  CatalogJoin,
  CatalogObject,
  Source,
} from "@/features/sources/types";
import { ApiError } from "@/lib/api";

type CatalogObjectDetailProps = {
  objectId: string;
};

export function CatalogObjectDetail({ objectId }: CatalogObjectDetailProps) {
  const t = useTranslate();
  const { open } = useNotification();
  const { data: canWrite } = useCan({
    resource: ModuleId.catalog,
    action: ModuleAction.edit,
  });
  const writable = Boolean(canWrite?.can);

  const [object, setObject] = useState<CatalogObject | null>(null);
  const [joins, setJoins] = useState<CatalogJoin[]>([]);
  const [source, setSource] = useState<Source | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [activeTab, setActiveTab] = useState<string | null>("overview");

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const [objRes, joinRes, sourcesRes] = await Promise.all([
        getCatalogObject(objectId),
        listObjectJoins(objectId),
        listSources(),
      ]);
      setObject(objRes.object);
      setJoins(joinRes.items);
      setSource(
        sourcesRes.items.find((s) => s.id === objRes.object.source_id) ?? null,
      );
    } catch (err) {
      setError(err instanceof ApiError ? err.detail : String(err));
    } finally {
      setLoading(false);
    }
  }, [objectId]);

  useEffect(() => {
    void load();
  }, [load]);

  const title = useMemo(() => {
    if (!object) return t("catalog.detail");
    return `${object.schema_name}.${object.name}`;
  }, [object, t]);

  const copyLocator = async () => {
    if (!object) return;
    try {
      await navigator.clipboard.writeText(object.locator_key);
      open?.({ type: "success", message: t("catalog.copied") });
    } catch (err) {
      open?.({
        type: "error",
        message: err instanceof Error ? err.message : String(err),
      });
    }
  };

  if (loading) return <PageLoader />;
  if (error) return <PageError message={error} />;
  if (!object) return <PageError message={t("catalog.empty")} />;

  return (
    <PageChrome
      title={title}
      description={object.business_name ?? undefined}
      actions={
        <Group gap="xs">
          <Button
            component={Link}
            href="/console/catalog"
            variant="default"
            size="sm"
          >
            {t("catalog.backToList")}
          </Button>
          <Button size="sm" variant="light" onClick={() => void load()}>
            {t("catalog.refresh")}
          </Button>
        </Group>
      }
    >
      <Stack gap="md">
        <Group gap="sm" wrap="wrap">
          <Badge variant="light">{object.object_type}</Badge>
          <Badge color={object.is_present ? "green" : "gray"}>
            {object.is_present
              ? t("catalog.fields.presentValue")
              : t("catalog.fields.absentValue")}
          </Badge>
          <Badge
            color={object.business_semantics_ready ? "green" : "gray"}
          >
            {object.business_semantics_ready
              ? t("catalog.semantics.ready")
              : t("catalog.semantics.notReady")}
          </Badge>
          <Text size="sm" c="dimmed">
            {t("catalog.semantics.provenance")}: {object.semantic_source ?? "—"}
          </Text>
          {object.semantics_updated_at ? (
            <Text size="sm" c="dimmed">
              {t("catalog.semantics.updatedAt")}: {object.semantics_updated_at}
            </Text>
          ) : null}
          {object.collected_at ? (
            <Text size="sm" c="dimmed">
              {t("catalog.structure.collectedAt")}: {object.collected_at}
            </Text>
          ) : null}
        </Group>
        <Group gap="xs" wrap="nowrap">
          <Text
            size="xs"
            c="dimmed"
            style={{ wordBreak: "break-all", flex: 1 }}
          >
            {object.locator_key}
          </Text>
          <Tooltip label={t("catalog.copyLocator")}>
            <ActionIcon
              variant="subtle"
              size="sm"
              onClick={() => void copyLocator()}
              aria-label={t("catalog.copyLocator")}
            >
              ⎘
            </ActionIcon>
          </Tooltip>
        </Group>

        <Tabs value={activeTab} onChange={setActiveTab} keepMounted>
          <Tabs.List>
            <Tabs.Tab value="overview">{t("catalog.tabs.overview")}</Tabs.Tab>
            <Tabs.Tab value="columns">{t("catalog.tabs.columns")}</Tabs.Tab>
            <Tabs.Tab value="sample">{t("catalog.tabs.sample")}</Tabs.Tab>
            <Tabs.Tab value="joins">{t("catalog.tabs.joins")}</Tabs.Tab>
            <Tabs.Tab value="ddl">{t("catalog.tabs.ddl")}</Tabs.Tab>
          </Tabs.List>

          <Tabs.Panel value="overview" pt="md">
            <OverviewTab
              object={object}
              writable={writable}
              onSaved={(next) => setObject(next)}
            />
          </Tabs.Panel>
          <Tabs.Panel value="columns" pt="md">
            <ColumnsTab
              object={object}
              writable={writable}
              onSaved={(next) => setObject(next)}
            />
          </Tabs.Panel>
          <Tabs.Panel value="sample" pt="md">
            <SampleTab object={object} source={source} />
          </Tabs.Panel>
          <Tabs.Panel value="joins" pt="md">
            <JoinsTab
              object={object}
              joins={joins}
              writable={writable}
              onJoinsChanged={setJoins}
            />
          </Tabs.Panel>
          <Tabs.Panel value="ddl" pt="md">
            <DdlTab ddl={object.ddl} />
          </Tabs.Panel>
        </Tabs>
      </Stack>
    </PageChrome>
  );
}
