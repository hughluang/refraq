"use client";

import {
  ActionIcon,
  Badge,
  Button,
  Group,
  Tabs,
  Text,
  Tooltip,
} from "@mantine/core";
import { useCan, useNotification, useTranslate } from "@refinedev/core";
import Link from "next/link";
import { useCallback, useEffect, useMemo, useState } from "react";

import { PageError } from "@/components/feedback/PageError";
import { PageBodySkeleton } from "@/components/feedback/PageBodySkeleton";
import { FillColumn } from "@/components/layout/FillColumn";
import { PageChrome } from "@/components/layout/PageChrome";
import {
  isAccessEvaluationPending,
  ModuleAction,
  ModuleId,
} from "@/features/console/module-identity";
import { getCatalogObject } from "@/features/sources/api/catalog";
import {
  catalogPresence,
  catalogSemanticsReady,
} from "@/features/sources/catalog-detail/catalogStatus";
import { ColumnsTab } from "@/features/sources/catalog-detail/ColumnsTab";
import { DdlTab } from "@/features/sources/catalog-detail/DdlTab";
import { JoinsTab } from "@/features/sources/catalog-detail/JoinsTab";
import { OverviewTab } from "@/features/sources/catalog-detail/OverviewTab";
import { isSampleEligible } from "@/features/sources/catalog-detail/catalogObjectKind";
import { SampleTab } from "@/features/sources/catalog-detail/SampleTab";
import type { CatalogObject } from "@/features/sources/types";
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
  const { data: canSampleData, isLoading: canSampleLoading } = useCan({
    resource: ModuleId.catalog,
    action: ModuleAction.sample,
  });
  const canSamplePending = isAccessEvaluationPending(
    canSampleLoading,
    canSampleData,
  );
  const writable = Boolean(canWrite?.can);

  const [object, setObject] = useState<CatalogObject | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [activeTab, setActiveTab] = useState<string | null>("overview");
  const [reloadEpoch, setReloadEpoch] = useState(0);
  const [joinsVisited, setJoinsVisited] = useState(false);
  const sampleEligible = object
    ? isSampleEligible(object.object_type)
    : true;
  const showSampleTab =
    sampleEligible && (canSamplePending || Boolean(canSampleData?.can));

  const load = useCallback(
    async (opts?: { refresh?: boolean }) => {
      const refresh = Boolean(opts?.refresh);
      if (!refresh) {
        setLoading(true);
      }
      setError(null);
      try {
        const objRes = await getCatalogObject(objectId);
        setObject(objRes.object);
        if (refresh) {
          setReloadEpoch((n) => n + 1);
        }
      } catch (err) {
        setError(err instanceof ApiError ? err.detail : String(err));
        if (!refresh) {
          setObject(null);
        }
      } finally {
        setLoading(false);
      }
    },
    [objectId],
  );

  useEffect(() => {
    setReloadEpoch(0);
    setJoinsVisited(false);
    setActiveTab("overview");
    void load();
  }, [load]);

  useEffect(() => {
    if (activeTab === "joins") {
      setJoinsVisited(true);
    }
  }, [activeTab]);

  useEffect(() => {
    if (!showSampleTab && activeTab === "sample") {
      setActiveTab("overview");
    }
  }, [showSampleTab, activeTab]);

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

  if (loading) {
    return (
      <PageChrome title={t("catalog.detail")}>
        <PageBodySkeleton />
      </PageChrome>
    );
  }
  if (error) {
    return (
      <PageChrome title={t("catalog.detail")}>
        <PageError message={error} onRetry={() => void load()} />
      </PageChrome>
    );
  }
  if (!object) {
    return (
      <PageChrome title={t("catalog.detail")}>
        <PageError message={t("catalog.empty")} />
      </PageChrome>
    );
  }

  const presence = catalogPresence(object.is_present);
  const semanticsReady = catalogSemanticsReady(
    Boolean(object.business_semantics_ready),
  );

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
          <Button
            size="sm"
            variant="light"
            onClick={() => void load({ refresh: true })}
          >
            {t("catalog.refresh")}
          </Button>
        </Group>
      }
    >
      <FillColumn gap="md">
        <Group gap="sm" wrap="wrap">
          <Badge variant="light">{object.object_type}</Badge>
          <Badge color={presence.color}>{t(presence.labelKey)}</Badge>
          <Badge color={semanticsReady.color}>
            {t(semanticsReady.labelKey)}
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

        <Tabs
          value={activeTab}
          onChange={setActiveTab}
          keepMounted
          style={{
            flex: 1,
            minHeight: 0,
            display: "flex",
            flexDirection: "column",
          }}
          styles={{
            panel: {
              flex: 1,
              minHeight: 0,
              overflow: "auto",
              display: "flex",
              flexDirection: "column",
            },
          }}
        >
          <Tabs.List>
            <Tabs.Tab value="overview">{t("catalog.tabs.overview")}</Tabs.Tab>
            <Tabs.Tab value="columns">{t("catalog.tabs.columns")}</Tabs.Tab>
            {showSampleTab ? (
              <Tabs.Tab value="sample">{t("catalog.tabs.sample")}</Tabs.Tab>
            ) : null}
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
          <Tabs.Panel value="columns" pt="md" style={{ overflow: "hidden" }}>
            <ColumnsTab
              object={object}
              writable={writable}
              reloadEpoch={reloadEpoch}
              onSaved={(next) => setObject(next)}
            />
          </Tabs.Panel>
          {showSampleTab ? (
            <Tabs.Panel value="sample" pt="md">
              <SampleTab object={object} />
            </Tabs.Panel>
          ) : null}
          <Tabs.Panel value="joins" pt="md" style={{ overflow: "hidden" }}>
            <JoinsTab
              object={object}
              writable={writable}
              listEnabled={joinsVisited}
            />
          </Tabs.Panel>
          <Tabs.Panel value="ddl" pt="md">
            <DdlTab ddl={object.ddl} />
          </Tabs.Panel>
        </Tabs>
      </FillColumn>
    </PageChrome>
  );
}
