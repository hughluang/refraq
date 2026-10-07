"use client";

import { Alert, Box, Stack, Text } from "@mantine/core";
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
import { PageError } from "@/components/feedback/PageError";
import { listEntities } from "@/features/entities/api";
import { listRoles } from "@/features/roles/api";
import { listSubjectAttributes, listUserGroups } from "@/features/subjects/api";
import { listUsers } from "@/features/users/api";

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
  const [users, setUsers] = useState<AccessOption[]>([]);
  const [roles, setRoles] = useState<AccessOption[]>([]);
  const [groups, setGroups] = useState<AccessOption[]>([]);
  const [subjectAttrs, setSubjectAttrs] = useState<AccessOption[]>([]);
  const [entities, setEntities] = useState<AccessOption[]>([]);

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
    const optionsFailed = (err: unknown) => setOptionsError(accessProblemText(err, t));
    setOptionsError(null);
    void listUsers({ limit: 100, offset: 0 })
      .then((page) =>
        setUsers(page.items.map((row) => ({ value: row.id, label: row.display_name || row.account }))),
      )
      .catch(optionsFailed);
    void listRoles({ limit: 100, offset: 0 })
      .then((page) => setRoles(page.items.map((row) => ({ value: row.id, label: row.name }))))
      .catch(optionsFailed);
    void listUserGroups({ limit: 100, offset: 0 })
      .then((page) => setGroups(page.items.map((row) => ({ value: row.id, label: row.name }))))
      .catch(optionsFailed);
    void listSubjectAttributes({ limit: 100, offset: 0 })
      .then((page) =>
        setSubjectAttrs(page.items.map((row) => ({ value: row.key, label: row.name }))),
      )
      .catch(optionsFailed);
    void listEntities({ limit: 100, offset: 0 })
      .then((page) =>
        setEntities(
          page.items
            .filter((row) => row.id !== entityId)
            .map((row) => ({ value: row.id, label: row.name })),
        ),
      )
      .catch(optionsFailed);
  }, [entityId, reload, t]);

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

  if (!summary) {
    return loadError ? (
      <PageError message={loadError} onRetry={() => void reload()} />
    ) : (
      <Text>{t("entities.access.loading")}</Text>
    );
  }

  return (
    <Stack gap="xl">
      {loadError ? <Alert color="red">{loadError}</Alert> : null}
      {optionsError ? <Alert color="red">{optionsError}</Alert> : null}
      <AccessPolicySummary summary={summary} />
      <AccessOrientation
        summary={summary}
        dismissed={guideDismissed}
        onDismiss={() => setGuideDismissed(true)}
        onFocus={focusSection}
      />
      <Box id="access-grants" style={{ scrollMarginTop: 72 }}>
        <AccessGrantsSection
          entityId={entityId}
          summary={summary}
          users={users}
          roles={roles}
          groups={groups}
          subjectAttrs={subjectAttrs}
          busyId={busyId}
          run={run}
          focusId={focus.id}
          focusNonce={focus.nonce}
        />
      </Box>
      <Box id="access-profiles" style={{ scrollMarginTop: 72 }}>
        <AccessProfilesSection
          entityId={entityId}
          summary={summary}
          entities={entities}
          busyId={busyId}
          run={run}
          onOptionsError={setOptionsError}
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
        />
      </Box>
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
      <Box id="access-preview" style={{ scrollMarginTop: 72 }}>
        <AccessPreviewSection
          entityId={entityId}
          users={users}
          canPreviewRows={canPreviewRows}
          busyId={busyId}
          run={run}
        />
      </Box>
    </Stack>
  );
}
