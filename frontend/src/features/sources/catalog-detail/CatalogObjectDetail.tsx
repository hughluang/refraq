"use client";

import {
  ActionIcon,
  Badge,
  Button,
  Group,
  Text,
  Tooltip,
} from "@mantine/core";
import { useCan, useNotification, useTranslate } from "@refinedev/core";
import { useCallback, useEffect, useMemo, useState } from "react";

import { Instant } from "@/components/display/Instant";
import { FillColumn } from "@/components/layout/FillColumn";
import { PageTabs, useConsoleTab, type PageTabItem } from "@/components/layout/consoleTabs";
import { StatusBadge } from "@/components/display/StatusBadge";
import {
  presentCatalogPresence,
  presentCatalogSemantics,
} from "@/components/display/statusTone";
import { PageChrome } from "@/components/layout/PageChrome";
import { ConsoleLink } from "@/components/navigation/ConsoleLink";
import { objectTypeLabel, semanticSourceLabel } from "@/features/sources/catalogLabel";
import {
  isAccessEvaluationPending,
  ModuleAction,
  ModuleId,
} from "@/features/console/module-identity";
import { getCatalogObject } from "@/features/sources/api/catalog";
import { ColumnsTab } from "@/features/sources/catalog-detail/ColumnsTab";
import { DdlTab } from "@/features/sources/catalog-detail/DdlTab";
import { HistoryTab } from "@/features/sources/catalog-detail/HistoryTab";
import { JoinsTab } from "@/features/sources/catalog-detail/JoinsTab";
import { OverviewTab } from "@/features/sources/catalog-detail/OverviewTab";
import { isSampleEligible } from "@/features/sources/catalog-detail/catalogObjectKind";
import { SampleTab } from "@/features/sources/catalog-detail/SampleTab";
import type { CatalogObject } from "@/features/sources/types";
import { problemMessage } from "@/lib/problem";
import { copyText } from "@/lib/copy-text";

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
  const [reloadEpoch, setReloadEpoch] = useState(0);
  const [joinsVisited, setJoinsVisited] = useState(false);
  const [historyVisited, setHistoryVisited] = useState(false);
  const sampleEligible = object
    ? isSampleEligible(object.object_type)
    : true;
  const showSampleTab =
    sampleEligible && (canSamplePending || Boolean(canSampleData?.can));
  const catalogTabs = useMemo(() => {
    const items = [{ value: "overview" }, { value: "columns" }];
    if (showSampleTab) items.push({ value: "sample" });
    items.push({ value: "joins" }, { value: "ddl" }, { value: "history" });
    return items;
  }, [showSampleTab]);
  const { value: activeTab, setTab } = useConsoleTab(catalogTabs);

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
        setError(problemMessage(t, err, String(err)));
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
    setHistoryVisited(false);
    void load();
  }, [load]);

  useEffect(() => {
    if (activeTab === "joins") {
      setJoinsVisited(true);
    }
    if (activeTab === "history") {
      setHistoryVisited(true);
    }
  }, [activeTab]);

  useEffect(() => {
    if (!showSampleTab && activeTab === "sample") {
      setTab("overview");
    }
  }, [showSampleTab, activeTab]);

  const title = useMemo(() => {
    if (!object) return t("catalog.detail");
    return `${object.schema_name}.${object.name}`;
  }, [object, t]);

  const copyLocator = async () => {
    if (!object) return;
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

  if (loading || error || !object) {
    return (
      <PageChrome
        title={t("catalog.detail")}
        status={loading ? "loading" : error ? "error" : "notFound"}
        errorMessage={error ?? undefined}
        onRetry={error ? () => void load() : undefined}
      />
    );
  }

  const presence = presentCatalogPresence(object.is_present);
  const semanticsReady = presentCatalogSemantics(
    Boolean(object.business_semantics_ready),
  );
  const detailTabs: PageTabItem[] = [
    {
      value: "overview",
      label: t("catalog.tabs.overview"),
      panel: (
        <OverviewTab
          object={object}
          writable={writable}
          onSaved={(next) => setObject(next)}
        />
      ),
    },
    {
      value: "columns",
      label: t("catalog.tabs.columns"),
      panel: (
        <ColumnsTab
          object={object}
          writable={writable}
          reloadEpoch={reloadEpoch}
          onSaved={(next) => setObject(next)}
        />
      ),
    },
  ];
  if (showSampleTab) {
    detailTabs.push({
      value: "sample",
      label: t("catalog.tabs.sample"),
      panel: <SampleTab object={object} />,
    });
  }
  detailTabs.push(
    {
      value: "joins",
      label: t("catalog.tabs.joins"),
      panel: (
        <JoinsTab object={object} writable={writable} listEnabled={joinsVisited} />
      ),
    },
    {
      value: "ddl",
      label: t("catalog.tabs.ddl"),
      panel: <DdlTab ddl={object.ddl} />,
    },
    {
      value: "history",
      label: t("catalog.tabs.history"),
      panel: <HistoryTab objectId={object.id} listEnabled={historyVisited} />,
    },
  );

  return (
    <PageTabs fill value={activeTab} onChange={setTab} tabs={detailTabs}>
      {({ list, panels }) => (
    <PageChrome
      title={t("catalog.title")}
      recordTitle={title}
      description={object.business_name ?? undefined}
      recent={{ moduleId: "catalog", title }}
      fill
      tabs={list}
      actions={
        <Group gap="xs">
          <Button
            component={ConsoleLink}
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
          <Badge variant="light">{objectTypeLabel(t, object.object_type)}</Badge>
          <StatusBadge tone={presence.tone} labelKey={presence.labelKey} />
          <StatusBadge tone={semanticsReady.tone} labelKey={semanticsReady.labelKey} />
          <Text size="sm" c="dimmed">
            {t("catalog.semantics.provenance")}:{" "}
            {object.semantic_source
              ? semanticSourceLabel(t, object.semantic_source)
              : "—"}
          </Text>
          {object.semantics_updated_at ? (
            <Text size="sm" c="dimmed">
              {t("catalog.semantics.updatedAt")}:{" "}
              <Instant value={object.semantics_updated_at} />
            </Text>
          ) : null}
          {object.collected_at ? (
            <Text size="sm" c="dimmed">
              {t("catalog.structure.collectedAt")}:{" "}
              <Instant value={object.collected_at} />
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

        {panels}
      </FillColumn>
    </PageChrome>
      )}
    </PageTabs>
  );
}
