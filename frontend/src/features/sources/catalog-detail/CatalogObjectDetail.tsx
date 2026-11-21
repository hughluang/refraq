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
import { useCallback, useEffect, useMemo, useRef, useState } from "react";

import { RepeatIcon } from "@/components/icons";
import { Instant } from "@/components/display/Instant";
import { FillColumn } from "@/components/layout/FillColumn";
import { PageTabs, useConsoleTab, type PageTabItem } from "@/components/layout/consoleTabs";
import { StatusBadge } from "@/components/display/StatusBadge";
import {
  presentCatalogPresence,
  presentCatalogSemantics,
} from "@/components/display/statusTone";
import { presentProblemNotification } from "@/components/feedback/presentProblemNotification";
import { PageChrome } from "@/components/layout/PageChrome";
import { ConsoleLink } from "@/components/navigation/ConsoleLink";
import { objectTypeLabel, semanticSourceLabel } from "@/features/sources/catalogLabel";
import {
  isAccessEvaluationPending,
  ModuleAction,
  ModuleId,
} from "@/features/console/module-identity";
import { MirrorSwitch } from "@/features/mirrors/MirrorSwitch";
import { resolveCatalogObject, setCatalogMirrorEnabled } from "@/features/sources/api/catalog";
import { ColumnsTab } from "@/features/sources/catalog-detail/ColumnsTab";
import { DdlTab } from "@/features/sources/catalog-detail/DdlTab";
import { HistoryTab } from "@/features/sources/catalog-detail/HistoryTab";
import { JoinsTab } from "@/features/sources/catalog-detail/JoinsTab";
import { OverviewTab } from "@/features/sources/catalog-detail/OverviewTab";
import { isSampleEligible } from "@/features/sources/catalog-detail/catalogObjectKind";
import { SampleTab } from "@/features/sources/catalog-detail/SampleTab";
import type { CatalogObject } from "@/features/sources/types";
import { ApiError } from "@/lib/api";
import { copyText } from "@/lib/copy-text";

type CatalogObjectDetailProps = {
  objectId: string;
};

export function CatalogObjectDetail({ objectId }: CatalogObjectDetailProps) {
  return <CatalogObjectRecord key={objectId} objectId={objectId} />;
}

function CatalogObjectRecord({ objectId }: CatalogObjectDetailProps) {
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
  // Semantics edits replace the object with a response that lacks this projection.
  const [mirror, setMirror] = useState<CatalogObject["mirror"]>(null);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [savingMirror, setSavingMirror] = useState(false);
  const [failed, setFailed] = useState(false);
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

  const request = useRef<AbortController | null>(null);
  const mirrorRequest = useRef<AbortSignal | null>(null);
  const load = useCallback(
    async (opts?: { refresh?: boolean }) => {
      request.current?.abort();
      mirrorRequest.current = null;
      setSavingMirror(false);
      const controller = new AbortController();
      request.current = controller;
      const refresh = Boolean(opts?.refresh);
      setRefreshing(refresh);
      if (!refresh) {
        setLoading(true);
      }
      setFailed(false);
      try {
        const objRes = await resolveCatalogObject(objectId, controller.signal);
        if (controller.signal.aborted) return;
        setObject(objRes.object);
        setMirror(objRes.object?.mirror);
        if (refresh) {
          setReloadEpoch((n) => n + 1);
        }
      } catch (err) {
        if (controller.signal.aborted) return;
        setFailed(true);
        if (!refresh || (err instanceof ApiError && [401, 403, 404].includes(err.status))) {
          setObject(null);
        }
        presentProblemNotification(t, err, { onRetry: () => {
          if (!controller.signal.aborted) void load();
        } });
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

  const saveMirror = async (enabled: boolean) => {
    const signal = request.current?.signal;
    if (
      !object || !mirror || !(enabled ? mirror.can_enable : mirror.can_disable) || !canWriteMirror?.can || refreshing ||
      !signal || signal.aborted || mirrorRequest.current
    ) return;
    mirrorRequest.current = signal;
    setSavingMirror(true);
    try {
      const accepted = await setCatalogMirrorEnabled(object.id, enabled, signal);
      if (signal.aborted) return;
      setMirror(accepted.mirror);
      open?.({ type: "success", message: t("catalog.mirror.accepted") });
    } catch (err) {
      if (signal.aborted) return;
      presentProblemNotification(t, err);
      void load({ refresh: true });
    } finally {
      if (mirrorRequest.current === signal) {
        mirrorRequest.current = null;
        setSavingMirror(false);
      }
    }
  };

  if (loading || failed || !object) {
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
    <PageTabs fill scrollable value={activeTab} onChange={setTab} tabs={detailTabs}>
      {({ list, panels }) => (
        <PageChrome
          title={t("catalog.title")}
          recordTitle={title}
          titleBasis="10rem"
          description={object.business_name ?? undefined}
          recent={{ moduleId: "catalog", title }}
          fill
          tabs={list}
          actions={
            <Group gap="xs">
              {mirror && (canReadMirror?.can || canWriteMirror?.can) ? (
                <MirrorSwitch
                  enabled={mirror.enabled}
                  disabled={savingMirror || refreshing || !canWriteMirror?.can || !(mirror.enabled ? mirror.can_disable : mirror.can_enable)}
                  table={title}
                  onChange={enabled => void saveMirror(enabled)}
                />
              ) : null}
              {!refreshing && canReadMirror?.can && mirror?.mirror_id ? (
                <Button
                  component={ConsoleLink}
                  href={`/console/mirrors/${encodeURIComponent(mirror.mirror_id)}`}
                  size="sm"
                  variant="light"
                >
                  {t("catalog.mirror.view")}
                </Button>
              ) : null}
              <Button
                component={ConsoleLink}
                href="/console/catalog"
                variant="default"
                size="sm"
                aria-label={t("catalog.backToList")}
              >
                <Text component="span" visibleFrom="sm">{t("catalog.backToList")}</Text>
                <Text component="span" hiddenFrom="sm">←</Text>
              </Button>
              <Button
                size="sm"
                variant="light"
                disabled={savingMirror}
                onClick={() => {
                  if (!mirrorRequest.current) void load({ refresh: true });
                }}
                aria-label={t("catalog.refresh")}
              >
                <Text component="span" visibleFrom="sm">{t("catalog.refresh")}</Text>
                <Text component="span" hiddenFrom="sm"><RepeatIcon /></Text>
              </Button>
            </Group>
          }
        >
          <FillColumn gap="md">
            <details style={{ flexShrink: 0 }}>
              <summary style={{ cursor: "pointer" }}>
                <Group gap="sm" wrap="wrap" component="span" display="inline-flex">
                  <Badge variant="light">{objectTypeLabel(t, object.object_type)}</Badge>
                  <StatusBadge tone={presence.tone} labelKey={presence.labelKey} />
                  <StatusBadge tone={semanticsReady.tone} labelKey={semanticsReady.labelKey} />
                </Group>
              </summary>
              <Group gap="sm" wrap="wrap" mt="sm">
                <Text size="sm" c="dimmed">
                  {t("catalog.semantics.provenance")}: {" "}
                  {object.semantic_source ? semanticSourceLabel(t, object.semantic_source) : "—"}
                </Text>
                {object.semantics_updated_at ? (
                  <Text size="sm" c="dimmed">
                    {t("catalog.semantics.updatedAt")}: {" "}
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
                <Text size="xs" c="dimmed" style={{ wordBreak: "break-all", flex: 1 }}>
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
            </details>
            {panels}
          </FillColumn>
        </PageChrome>
      )}
    </PageTabs>
  );
}
