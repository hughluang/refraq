"use client";

import { Badge, Button, Group, Progress, Skeleton, Stack, Text } from "@mantine/core";
import { useNotification, useTranslate } from "@refinedev/core";
import { useEffect, useRef, useState } from "react";

import { StatusBadge } from "@/components/display/StatusBadge";
import { presentProblemNotification } from "@/components/feedback/presentProblemNotification";
import { PlusIcon, ShieldLockIcon } from "@/components/icons";
import { AccessInspector } from "@/features/entities/AccessInspector";
import { SignalTopology } from "@/features/entities/SignalTopology";
import { SpecimenLens } from "@/features/entities/SpecimenLens";
import {
  combinationBudgetVisible,
  viewsNeedAttention,
  viewsStatusKey,
} from "@/features/entities/accessLogic";
import {
  openAccessWorkbench,
  type AccessPort,
  type AccessWorkbenchSession,
  type AccessWorkbenchSnapshot,
  type LiveSchedulePort,
} from "@/features/entities/accessWorkbench";

import classes from "./AccessWorkbench.module.css";

type Props = {
  entityId: string;
  canPreviewRows: boolean;
  port?: AccessPort;
  schedule?: LiveSchedulePort;
};

export function EntityAccessTab({ entityId, canPreviewRows, port, schedule }: Props) {
  const t = useTranslate();
  const { open } = useNotification();
  const sessionRef = useRef<AccessWorkbenchSession | null>(null);
  const lastNotifyIdRef = useRef<number>(0);

  const [snapshot, setSnapshot] = useState<AccessWorkbenchSnapshot>(() => ({
    entityId,
    canPreviewRows,
    phase: "loading",
    summary: null,
    freshness: "current",
    busyId: null,
    selection: null,
    pin: { kind: "profiles" },
    hover: null,
    preview: null,
    previewBusy: false,
    lastCopyDropped: [],
    lastNotification: null,
  }));

  useEffect(() => {
    const session = openAccessWorkbench({
      entityId,
      canPreviewRows,
      port,
      schedule,
    });
    sessionRef.current = session;
    lastNotifyIdRef.current = 0;
    setSnapshot(session.snapshot());
    const unsub = session.subscribe(() => {
      setSnapshot(session.snapshot());
    });
    return () => {
      unsub();
      session.dispose();
      sessionRef.current = null;
    };
  }, [entityId, canPreviewRows, port, schedule]);

  useEffect(() => {
    const note = snapshot.lastNotification;
    if (!note || note.id === lastNotifyIdRef.current) return;
    lastNotifyIdRef.current = note.id;
    if (note.type === "success") {
      open?.({
        type: "success",
        message: note.savedKey ? t(note.savedKey) : t("entities.access.saved"),
      });
      return;
    }
    if (note.retry === "load") {
      presentProblemNotification(t, note.error, {
        onRetry: () => void sessionRef.current?.dispatch({ kind: "reload" }),
      });
      return;
    }
    if (note.retry === "preview") {
      presentProblemNotification(t, note.error, {
        onRetry: () => void sessionRef.current?.dispatch({ kind: "refresh_preview" }),
      });
      return;
    }
    presentProblemNotification(t, note.error);
  }, [snapshot.lastNotification, open, t]);

  const dispatch: AccessWorkbenchSession["dispatch"] = (intent) => {
    const current = sessionRef.current;
    if (!current) return Promise.resolve(false);
    return current.dispatch(intent);
  };

  if (snapshot.phase === "loading" && !snapshot.summary) {
    return (
      <Stack gap="md">
        <Skeleton height={40} />
        <Skeleton height={220} />
        <Skeleton height={200} />
      </Stack>
    );
  }

  if (snapshot.phase === "unloaded" && !snapshot.summary) {
    return (
      <Group justify="center" py="xl">
        <Button
          variant="default"
          onClick={() => void dispatch({ kind: "reload" })}
        >
          {t("status.unloaded")}
        </Button>
      </Group>
    );
  }

  const summary = snapshot.summary;
  if (!summary) return null;

  const attention = viewsNeedAttention(summary);
  const viewKey = viewsStatusKey(summary);
  const showBudget =
    combinationBudgetVisible(summary.views) || summary.views.combinations > 0;
  const overLimit =
    summary.views.subjects_over_limit > 0 ||
    summary.views.combinations > summary.views.combination_limit;
  const ratio =
    summary.views.combination_limit > 0
      ? Math.min(100, Math.round((summary.views.combinations / summary.views.combination_limit) * 100))
      : 100;

  return (
    <div className={classes.workbench}>
      {/* Telemetry & Quick Actions */}
      <div className={classes.telemetryBar}>
        <Group gap="sm" wrap="wrap">
          {attention ? (
            <StatusBadge
              tone={
                summary.views.state === "failed"
                  ? "danger"
                  : summary.views.state === "pending"
                    ? "warning"
                    : "warning"
              }
              labelKey={viewKey}
              explanation={t(viewKey)}
            />
          ) : (
            <Badge size="sm" variant="light" color="green">
              {t("entities.access.views.ready")}
            </Badge>
          )}
          {snapshot.freshness === "stale" ? (
            <Badge size="xs" color="yellow" variant="outline">
              {t("status.stale")}
            </Badge>
          ) : null}
          {showBudget ? (
            <Group gap="xs" wrap="nowrap">
              <Text size="xs" c={overLimit ? "red" : "dimmed"}>
                {t("entities.access.combinations", {
                  count: summary.views.combinations,
                  limit: summary.views.combination_limit,
                })}
              </Text>
              <Progress
                w={72}
                size="sm"
                value={ratio}
                color={overLimit ? "red" : ratio >= 80 ? "yellow" : "blue"}
                aria-label={t("entities.access.combinations", {
                  count: summary.views.combinations,
                  limit: summary.views.combination_limit,
                })}
              />
            </Group>
          ) : null}
        </Group>

        <Group gap="xs" wrap="wrap">
          <Button
            size="xs"
            variant="light"
            leftSection={<PlusIcon size={13} />}
            onClick={() => void dispatch({ kind: "select", selection: { kind: "grant_new" } })}
          >
            {t("entities.access.grants.add")}
          </Button>
          <Button
            size="xs"
            variant="default"
            leftSection={<PlusIcon size={13} />}
            onClick={() => void dispatch({ kind: "select", selection: { kind: "profile_new" } })}
          >
            {t("entities.access.profiles.create")}
          </Button>
          <Button
            size="xs"
            variant="default"
            leftSection={<ShieldLockIcon size={13} />}
            onClick={() =>
              void dispatch({ kind: "select", selection: { kind: "restriction_new" } })
            }
          >
            {t("entities.access.workbench.addGuardrail")}
          </Button>
        </Group>
      </div>

      {/* Signal Topology + Contextual Inline Inspector */}
      <div
        className={`${classes.stageGrid} ${
          snapshot.selection ? classes.stageGridWithInspector : ""
        }`}
      >
        <SignalTopology
          summary={summary}
          selection={snapshot.selection}
          pin={snapshot.pin}
          hover={snapshot.hover}
          busyId={snapshot.busyId}
          dispatch={dispatch}
        />
        {snapshot.selection ? (
          <AccessInspector
            entityId={entityId}
            summary={summary}
            selection={snapshot.selection}
            busyId={snapshot.busyId}
            lastCopyDropped={snapshot.lastCopyDropped}
            dispatch={dispatch}
          />
        ) : null}
      </div>

      {/* Interactive Specimen Lens */}
      <SpecimenLens
        summary={summary}
        pin={snapshot.pin}
        selection={snapshot.selection}
        preview={snapshot.preview}
        previewBusy={snapshot.previewBusy}
        canPreviewRows={canPreviewRows}
        busyId={snapshot.busyId}
        dispatch={dispatch}
      />
    </div>
  );
}
