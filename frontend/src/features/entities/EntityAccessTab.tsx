"use client";

import { Alert, Box, Stack } from "@mantine/core";
import { useNotification, useTranslate } from "@refinedev/core";
import { useCallback, useEffect, useState } from "react";

import { AccessGrantsSection } from "@/features/entities/AccessGrantsSection";
import { AccessLaddersSection } from "@/features/entities/AccessLaddersSection";
import { AccessOrientation } from "@/features/entities/AccessOrientation";
import { AccessPolicySummary } from "@/features/entities/AccessPolicySummary";
import { AccessPreviewSection } from "@/features/entities/AccessPreviewSection";
import { AccessProfilesSection } from "@/features/entities/AccessProfilesSection";
import { AccessRestrictionsSection } from "@/features/entities/AccessRestrictionsSection";
import { getAccessSummary } from "@/features/entities/accessApi";
import { accessProblemText } from "@/features/entities/accessProblem";
import type { AccessSectionId } from "@/features/entities/accessLogic";
import type { AccessOption, AccessRun } from "@/features/entities/accessSession";
import type { AccessSummary } from "@/features/entities/accessTypes";
import { listAllSubjectAttributes } from "@/features/subjects/api";

type Props = {
  entityId: string;
  canPreviewRows: boolean;
};

export function EntityAccessTab({ entityId, canPreviewRows }: Props) {
  const t = useTranslate();
  const { open } = useNotification();
  const [summary, setSummary] = useState<AccessSummary | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [optionsError, setOptionsError] = useState<string | null>(null);
  const [busyId, setBusyId] = useState<string | null>(null);
  const [focus, setFocus] = useState<{ id: AccessSectionId; nonce: number }>({
    id: "grants",
    nonce: 0,
  });
  const [guideDismissed, setGuideDismissed] = useState(false);
  const [subjectAttrs, setSubjectAttrs] = useState<AccessOption[]>([]);

  const load = useCallback(async () => {
    const next = await getAccessSummary(entityId);
    setLoadError(null);
    setSummary(next);
  }, [entityId]);

  const reload = useCallback(
    () => load().catch((err: unknown) => setLoadError(accessProblemText(err, t))),
    [load, t],
  );

  const focusSection = (id: AccessSectionId) => {
    setFocus((current) => ({ id, nonce: current.nonce + 1 }));
  };

  useEffect(() => {
    setGuideDismissed(false);
  }, [entityId]);

  useEffect(() => {
    if (focus.nonce === 0) return;
    document.getElementById(`access-${focus.id}`)?.scrollIntoView({
      behavior: "smooth",
      block: "start",
    });
  }, [focus]);

  useEffect(() => {
    void reload();
  }, [reload]);

  useEffect(() => {
    let cancelled = false;
    setOptionsError(null);
    void listAllSubjectAttributes()
      .then((items) => {
        if (cancelled) return;
        setSubjectAttrs(items.map((row) => ({ value: row.key, label: row.name })));
      })
      .catch((err: unknown) => {
        if (!cancelled) setOptionsError(accessProblemText(err, t));
      });
    return () => {
      cancelled = true;
    };
  }, [t]);

  const notify = (ok: boolean, detail?: string) => {
    open?.({
      type: ok ? "success" : "error",
      message: ok ? detail || t("entities.access.saved") : t("entities.access.failed"),
      description: ok ? undefined : detail,
    });
  };

  const run: AccessRun = async (id, savedKey, work) => {
    setBusyId(id);
    try {
      await work();
      if (savedKey) {
        await load();
        notify(true, t(savedKey));
      }
      return true;
    } catch (err) {
      notify(false, accessProblemText(err, t));
      return false;
    } finally {
      setBusyId(null);
    }
  };

  const collectionLoading = summary == null && loadError == null;
  const collectionError = summary == null ? loadError : null;
  const reloadCollection = () => reload();

  return (
    <Stack gap="xl">
      {summary && loadError ? <Alert color="red">{loadError}</Alert> : null}
      {optionsError ? <Alert color="red">{optionsError}</Alert> : null}
      {summary ? <AccessPolicySummary summary={summary} /> : null}
      {summary ? (
        <AccessOrientation
          summary={summary}
          dismissed={guideDismissed}
          onDismiss={() => setGuideDismissed(true)}
          onFocus={focusSection}
        />
      ) : null}
      <Box id="access-grants" style={{ scrollMarginTop: 72 }}>
        <AccessGrantsSection
          entityId={entityId}
          summary={summary}
          subjectAttrs={subjectAttrs}
          busyId={busyId}
          run={run}
          focusId={focus.id}
          focusNonce={focus.nonce}
          loading={collectionLoading}
          error={collectionError}
          onReload={reloadCollection}
        />
      </Box>
      <Box id="access-profiles" style={{ scrollMarginTop: 72 }}>
        <AccessProfilesSection
          entityId={entityId}
          summary={summary}
          busyId={busyId}
          run={run}
          onOptionsError={setOptionsError}
          loading={collectionLoading}
          error={collectionError}
          onReload={reloadCollection}
        />
      </Box>
      <Box id="access-ladders" style={{ scrollMarginTop: 72 }}>
        <AccessLaddersSection
          entityId={entityId}
          summary={summary}
          busyId={busyId}
          run={run}
          focusId={focus.id}
          focusNonce={focus.nonce}
          loading={collectionLoading}
          error={collectionError}
          onReload={reloadCollection}
        />
      </Box>
      {summary ? (
        <Box id="access-restrictions" style={{ scrollMarginTop: 72 }}>
          <AccessRestrictionsSection
            entityId={entityId}
            summary={summary}
            busyId={busyId}
            run={run}
            focusId={focus.id}
            focusNonce={focus.nonce}
          />
        </Box>
      ) : null}
      {summary ? (
        <Box id="access-preview" style={{ scrollMarginTop: 72 }}>
          <AccessPreviewSection
            entityId={entityId}
            canPreviewRows={canPreviewRows}
            busyId={busyId}
            run={run}
          />
        </Box>
      ) : null}
    </Stack>
  );
}
