"use client";

import { Box, Stack } from "@mantine/core";
import { useNotification, useTranslate } from "@refinedev/core";
import { useCallback, useEffect, useRef, useState } from "react";

import { presentProblemNotification } from "@/components/feedback/presentProblemNotification";
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
import { presentConsoleNotification } from "@/providers/notification-provider";

type Props = {
  entityId: string;
  canPreviewRows: boolean;
};

export function EntityAccessTab({ entityId, canPreviewRows }: Props) {
  const t = useTranslate();
  const { open } = useNotification();
  const [summary, setSummary] = useState<AccessSummary | null>(null);
  const [loadFailed, setLoadFailed] = useState(false);
  const [busyId, setBusyId] = useState<string | null>(null);
  const [focus, setFocus] = useState<{ id: AccessSectionId; nonce: number }>({
    id: "grants",
    nonce: 0,
  });
  const [guideDismissed, setGuideDismissed] = useState(false);
  const [subjectAttrs, setSubjectAttrs] = useState<AccessOption[]>([]);

  const load = useCallback(async () => {
    const next = await getAccessSummary(entityId);
    setLoadFailed(false);
    setSummary(next);
  }, [entityId]);

  const reloadRef = useRef<() => Promise<void>>(async () => {});

  const reload = useCallback(() => {
    return load().catch((err: unknown) => {
      setLoadFailed(true);
      presentProblemNotification(t, err, { onRetry: () => void reloadRef.current() });
    });
  }, [load, t]);

  reloadRef.current = reload;

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

  const optionsGeneration = useRef(0);
  const loadOptionsRef = useRef<() => void>(() => {});

  const loadOptions = useCallback(() => {
    const generation = ++optionsGeneration.current;
    void listAllSubjectAttributes()
      .then((items) => {
        if (generation !== optionsGeneration.current) return;
        setSubjectAttrs(items.map((row) => ({ value: row.key, label: row.name })));
      })
      .catch((err: unknown) => {
        if (generation !== optionsGeneration.current) return;
        presentProblemNotification(t, err, { onRetry: () => loadOptionsRef.current() });
      });
  }, [t]);

  loadOptionsRef.current = loadOptions;

  useEffect(() => {
    loadOptions();
    return () => {
      optionsGeneration.current += 1;
    };
  }, [loadOptions]);

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

  const collectionLoading = summary == null && !loadFailed;
  const collectionError = summary == null && loadFailed ? "failed" : null;
  const reloadCollection = () => reload();

  return (
    <Stack gap="xl">
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
          onOptionsError={(message) => {
            presentConsoleNotification({ type: "error", title: message });
          }}
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
