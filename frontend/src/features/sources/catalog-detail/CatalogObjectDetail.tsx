"use client";

import {
  Badge,
  Button,
  Group,
} from "@mantine/core";
import { useCan, useTranslate } from "@refinedev/core";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";

import { StatusBadge } from "@/components/display/StatusBadge";
import {
  presentCatalogPresence,
  presentCatalogSemantics,
} from "@/components/display/statusTone";
import { presentProblemNotification } from "@/components/feedback/presentProblemNotification";
import { NavCollapseIcon, RepeatIcon } from "@/components/icons";
import { FillColumn } from "@/components/layout/FillColumn";
import { HeaderActions } from "@/components/layout/HeaderActions";
import { PageChrome } from "@/components/layout/PageChrome";
import {
  PageTabs,
  useConsoleTab,
  type PageTabItem,
} from "@/components/layout/consoleTabs";
import { ConsoleLink } from "@/components/navigation/ConsoleLink";
import {
  isAccessEvaluationPending,
  ModuleAction,
  ModuleId,
} from "@/features/console/module-identity";
import { MirrorTableDrawer } from "@/features/mirrors/MirrorTableDrawer";
import { resolveCatalogObject } from "@/features/sources/api/catalog";
import { ColumnsTab } from "@/features/sources/catalog-detail/ColumnsTab";
import { DdlTab } from "@/features/sources/catalog-detail/DdlTab";
import { HistoryTab } from "@/features/sources/catalog-detail/HistoryTab";
import { JoinsTab } from "@/features/sources/catalog-detail/JoinsTab";
import { OverviewTab } from "@/features/sources/catalog-detail/OverviewTab";
import { SampleTab } from "@/features/sources/catalog-detail/SampleTab";
import { isSampleEligible } from "@/features/sources/catalog-detail/catalogObjectKind";
import { objectTypeLabel } from "@/features/sources/catalogLabel";
import type { CatalogObject } from "@/features/sources/types";
import { ApiError } from "@/lib/api";

type CatalogObjectDetailProps = {
  objectId: string;
};

export type ExternalColumnFilterRequest = {
  filter: "all" | "empty";
  nonce: number;
};

export function CatalogObjectDetail({ objectId }: CatalogObjectDetailProps) {
  return <CatalogObjectRecord key={objectId} objectId={objectId} />;
}

function CatalogObjectRecord({ objectId }: CatalogObjectDetailProps) {
  const t = useTranslate();
  const { data: canWrite } = useCan({
    resource: ModuleId.catalog,
    action: ModuleAction.edit,
  });
  const { data: canSampleData, isLoading: canSampleLoading } = useCan({
    resource: ModuleId.catalog,
    action: ModuleAction.sample,
  });
  const { data: canReadMirror } = useCan({
    resource: ModuleId.mirrors,
    action: ModuleAction.show,
  });
  const { data: canWriteMirror } = useCan({
    resource: ModuleId.mirrors,
    action: ModuleAction.edit,
  });
  const canSamplePending = isAccessEvaluationPending(
    canSampleLoading,
    canSampleData,
  );
  const writable = Boolean(canWrite?.can);

  const [object, setObject] = useState<CatalogObject | null>(null);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [failed, setFailed] = useState(false);
  const [notFound, setNotFound] = useState(false);
  const [reloadEpoch, setReloadEpoch] = useState(0);
  const [joinsVisited, setJoinsVisited] = useState(false);
  const [historyVisited, setHistoryVisited] = useState(false);
  const [, setInspectedColumnId] = useState<string | null>(null);
  const [, setExternalFilterRequest] =
    useState<ExternalColumnFilterRequest | null>(null);

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

  const request = useRef<AbortController | null>(null);
  const load = useCallback(
    async (opts?: { refresh?: boolean }) => {
      request.current?.abort();
      const controller = new AbortController();
      request.current = controller;
      const refresh = Boolean(opts?.refresh);
      setRefreshing(refresh);
      if (!refresh) {
        setLoading(true);
      }
      setFailed(false);
      setNotFound(false);
      try {
        const objRes = await resolveCatalogObject(objectId, controller.signal);
        if (controller.signal.aborted) return;
        if (!objRes.object) {
          setObject(null);
          setNotFound(true);
          return;
        }
        setObject(objRes.object);
        if (refresh) {
          setReloadEpoch((n) => n + 1);
        }
      } catch (err) {
        if (controller.signal.aborted) return;
        if (err instanceof ApiError && err.status === 404) {
          setObject(null);
          setNotFound(true);
          return;
        }
        setFailed(true);
        if (
          !refresh ||
          (err instanceof ApiError && [401, 403].includes(err.status))
        ) {
          setObject(null);
        }
        presentProblemNotification(t, err, {
          onRetry: () => {
            if (!controller.signal.aborted) void load();
          },
        });
      } finally {
        if (!controller.signal.aborted) {
          setLoading(false);
          setRefreshing(false);
        }
      }
    },
    [objectId, t],
  );

  useEffect(() => {
    setReloadEpoch(0);
    setJoinsVisited(false);
    setHistoryVisited(false);
    setInspectedColumnId(null);
    setExternalFilterRequest(null);
    void load();
    return () => request.current?.abort();
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
  }, [showSampleTab, activeTab, setTab]);

  const handleOpenColumn = useCallback(
    (columnId: string, filter: "all" | "empty" = "all") => {
      setInspectedColumnId(columnId);
      setExternalFilterRequest({ filter, nonce: Date.now() });
      setTab("columns");
    },
    [setTab],
  );

  const title = useMemo(() => {
    if (!object) return objectId;
    return `${object.schema_name}.${object.name}`;
  }, [object, objectId]);

  if (loading || failed || notFound || !object) {
    return (
      <PageChrome
        title={t("catalog.detail")}
        status={loading ? "loading" : failed ? "unloaded" : "notFound"}
        onRetry={failed ? () => void load() : undefined}
      />
    );
  }

  const presence = presentCatalogPresence(object.is_present);
  const semanticsReady = presentCatalogSemantics(
    Boolean(object.business_semantics_ready),
  );
  const hasColumns =
    (object.object_type !== "procedure" && object.object_type !== "function") ||
    object.columns.length > 0;
  const backHref = `/console/catalog?source=${encodeURIComponent(object.source_id)}`;

  const detailTabs: PageTabItem[] = [
    {
      value: "overview",
      label: t("catalog.tabs.overview"),
      panel: (
        <OverviewTab
          object={object}
          writable={writable}
          onSaved={setObject}
          onOpenColumn={handleOpenColumn}
          onOpenTab={setTab}
          onOpenColumnsCoverage={(filter) => {
            setExternalFilterRequest({ filter, nonce: Date.now() });
            setTab("columns");
          }}
        />
      ),
    },
    {
      value: "columns",
      label: hasColumns
        ? t("catalog.detail.tabs.columnsCount", {
            count: object.columns.length,
          })
        : t("catalog.tabs.columns"),
      panel: (
        <ColumnsTab
          object={object}
          writable={writable}
          reloadEpoch={reloadEpoch}
          onSaved={setObject}
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
        <JoinsTab
          object={object}
          writable={writable}
          listEnabled={joinsVisited}
        />
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
    <PageTabs
      fill
      scrollable
      value={activeTab}
      onChange={setTab}
      tabs={detailTabs}
    >
      {({ list, panels }) => (
        <PageChrome
          title={t("catalog.title")}
          recordTitle={title}
          titleBasis="10rem"
          description={object.business_name || object.comment || undefined}
          titleExtra={
            <Group gap="xs" wrap="wrap">
              <Badge variant="default" size="sm">
                {objectTypeLabel(t, object.object_type)}
              </Badge>
              <StatusBadge
                tone={presence.tone}
                labelKey={presence.labelKey}
                size="sm"
              />
              <StatusBadge
                tone={
                  object.business_semantics_ready ? "success" : "warning"
                }
                labelKey={semanticsReady.labelKey}
                size="sm"
              />
            </Group>
          }
          recent={{ moduleId: "catalog", title }}
          fill
          tabs={list}
          actions={
            <HeaderActions
              navigation={
                <Group gap="xs" wrap="nowrap">
                  <Button
                    component={ConsoleLink}
                    href={backHref}
                    variant="subtle"
                    size="xs"
                    leftSection={<NavCollapseIcon size={14} />}
                  >
                    {t("catalog.backToList")}
                  </Button>
                  <Button
                    variant="default"
                    size="xs"
                    leftSection={<RepeatIcon size={14} />}
                    onClick={() => void load({ refresh: true })}
                    loading={refreshing}
                  >
                    {t("catalog.refresh")}
                  </Button>
                </Group>
              }
              lifecycle={
                object.mirror &&
                (canReadMirror?.can || canWriteMirror?.can) ? (
                  <MirrorTableDrawer
                    objectId={object.id}
                    disabled={refreshing}
                  />
                ) : undefined
              }
            />
          }
        >
          <FillColumn gap="md">
            {panels}
          </FillColumn>
        </PageChrome>
      )}
    </PageTabs>
  );
}
