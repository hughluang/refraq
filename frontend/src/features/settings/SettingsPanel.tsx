"use client";

import { Badge, Button, Group, Stack, Text } from "@mantine/core";
import {
  useCan,
  useNotification,
  useTranslate,
} from "@refinedev/core";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";

import { DisplayField } from "@/components/display/DisplayField";
import { StatusBadge } from "@/components/display/StatusBadge";
import { NumberField } from "@/components/form/NumberField";
import { SelectField } from "@/components/form/SelectField";
import { presentProblemNotification } from "@/components/feedback/presentProblemNotification";
import { presentSaveFailure } from "@/components/feedback/presentSaveFailure";
import { PageBodySkeleton } from "@/components/feedback/PageBodySkeleton";
import { useConsoleMutation } from "@/components/feedback/useConsoleMutation";
import { PageChrome } from "@/components/layout/PageChrome";
import { useLeaveGuardRegistration } from "@/components/navigation/leaveGuard";
import { ModuleAction, ModuleId } from "@/features/console/module-identity";
import {
  fetchPlatformSettings,
  patchPlatformSettings,
  resetPlatformSettings,
} from "@/features/settings/api";
import {
  admitIntegerDraft,
  dirtyParameterValues,
  enumSearchMissesCatalog,
  integerFallback,
  isStringEnum,
  storedIntegerViolatesConstraint,
} from "@/features/settings/constraint";
import type { SystemParameter } from "@/features/settings/types";
import { useShowInstant } from "@/hooks/useFormatInstant";
import { ApiError } from "@/lib/api";

function groupLabelKey(group: string): string {
  return `settings.group.${group}`;
}

function draftReasonKey(reason: string): string {
  return `settings.validation.draft.${reason}`;
}

export function SettingsPanel() {
  const t = useTranslate();
  const showInstant = useShowInstant();
  const { open } = useNotification();
  const resetAction = useConsoleMutation();
  const { data: canWrite } = useCan({
    resource: ModuleId.settings,
    action: ModuleAction.edit,
  });
  const [parameters, setParameters] = useState<SystemParameter[]>([]);
  const [drafts, setDrafts] = useState<Record<string, number | string>>({});
  const [enumSearch, setEnumSearch] = useState<Record<string, string>>({});
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [failed, setFailed] = useState(false);
  const loadRef = useRef<() => Promise<void>>(async () => {});

  const applyCatalog = useCallback((items: SystemParameter[]) => {
    setParameters(items);
    setDrafts(
      Object.fromEntries(
        items.map((item) => [
          item.key,
          isStringEnum(item.constraint)
            ? typeof item.value === "string"
              ? item.value
              : ""
            : typeof item.value === "number"
              ? item.value
              : "",
        ]),
      ),
    );
    setEnumSearch({});
  }, []);

  const load = useCallback(async () => {
    setLoading(true);
    setFailed(false);
    try {
      const data = await fetchPlatformSettings();
      applyCatalog(data.parameters);
    } catch (err) {
      setParameters([]);
      setFailed(true);
      presentProblemNotification(t, err, {
        onRetry: () => void loadRef.current(),
      });
    } finally {
      setLoading(false);
    }
  }, [applyCatalog, t]);

  loadRef.current = load;

  useEffect(() => {
    void load();
  }, [load]);

  const dirtyValues = useMemo(
    () => dirtyParameterValues(parameters, drafts),
    [drafts, parameters],
  );
  useLeaveGuardRegistration(Object.keys(dirtyValues).length > 0);

  const groups = useMemo(() => {
    const seen: string[] = [];
    for (const item of parameters) {
      if (!seen.includes(item.group)) {
        seen.push(item.group);
      }
    }
    return seen;
  }, [parameters]);

  async function onSave() {
    if (Object.keys(dirtyValues).length === 0) {
      return;
    }
    setSaving(true);
    try {
      const data = await patchPlatformSettings(dirtyValues);
      applyCatalog(data.parameters);
      open?.({
        type: "success",
        message: t("settings.title"),
        description: t("settings.save.success"),
      });
    } catch (err) {
      const api = err instanceof ApiError ? err : null;
      presentSaveFailure(t, err, () => ({
        mapped: [],
        unmapped: api?.status === 422 ? [...(api.details ?? [])] : [],
      }));
    } finally {
      setSaving(false);
    }
  }

  function onReset(key: string, name: string) {
    resetAction.run({
      safety: "confirm",
      key,
      recordName: name,
      title: t("settings.reset.confirmTitle", { name }),
      consequence: t("settings.reset.consequence"),
      confirmLabel: t("settings.reset"),
      outcome: t("settings.reset.outcome"),
      execute: async () => {
        const data = await resetPlatformSettings([key]);
        applyCatalog(data.parameters);
      },
    });
  }

  return (
    <PageChrome
      title={t("settings.title")}
      description={t("settings.description")}
      status={!loading && failed ? "unloaded" : "ready"}
      onRetry={() => void load()}
      actions={
        canWrite?.can ? (
          <Button
            size="sm"
            loading={saving}
            disabled={Object.keys(dirtyValues).length === 0}
            onClick={() => void onSave()}
          >
            {t("settings.save")}
          </Button>
        ) : undefined
      }
    >
      <Stack gap="lg">
        {resetAction.dialog}
        {loading ? <PageBodySkeleton rows={6} /> : null}
        {!loading && !failed
          ? groups.map((group) => (
              <Stack key={group} gap="md">
                <Text size="sm" fw={600}>
                  {t(groupLabelKey(group))}
                </Text>
                {parameters
                  .filter((item) => item.group === group)
                  .map((item) => {
                    const draft = drafts[item.key] ?? "";
                    const selected =
                      typeof draft === "string" ? draft : "";
                    const enumConstraint = isStringEnum(item.constraint);
                    const searchMisses =
                      enumConstraint &&
                      enumSearchMissesCatalog(
                        enumSearch[item.key] ?? "",
                        selected,
                        item.constraint.enum,
                      );
                    const admitted = enumConstraint
                      ? null
                      : admitIntegerDraft(draft, item.constraint);
                    const servedViolates = enumConstraint
                      ? typeof item.value === "string" &&
                        !item.constraint.enum?.includes(item.value)
                      : storedIntegerViolatesConstraint(
                          item.value,
                          item.constraint,
                        );
                    const effective = enumConstraint
                      ? item.seed
                      : integerFallback(
                          item.value,
                          item.constraint,
                          item.seed,
                        );
                    return (
                    <Stack key={item.key} gap="xs" p="sm">
                      {enumConstraint ? (
                        <SelectField
                          label={t(item.label_key)}
                          description={t(item.help_key)}
                          data={item.constraint.enum ?? []}
                          value={selected}
                          searchable
                          editable={Boolean(canWrite?.can)}
                          error={
                            searchMisses
                              ? t("settings.validation.draft.not_allowed")
                              : undefined
                          }
                          onSearchChange={(value) =>
                            setEnumSearch((current) => ({
                              ...current,
                              [item.key]: value,
                            }))
                          }
                          onChange={(value) => {
                            setDrafts((current) => ({
                              ...current,
                              [item.key]: value ?? "",
                            }));
                            setEnumSearch((current) => ({
                              ...current,
                              [item.key]: "",
                            }));
                          }}
                        />
                      ) : (
                      <NumberField
                        label={t(item.label_key)}
                        description={t(item.help_key)}
                        value={draft}
                        editable={Boolean(canWrite?.can)}
                        onChange={(value) =>
                          setDrafts((current) => ({
                            ...current,
                            [item.key]: value,
                          }))
                        }
                        min={item.constraint.minimum}
                        max={item.constraint.maximum}
                        allowDecimal={false}
                        error={
                          admitted && !admitted.ok && draft !== item.value
                            ? t(draftReasonKey(admitted.reason), {
                                min: item.constraint.minimum,
                                max: item.constraint.maximum,
                              })
                            : undefined
                        }
                      />
                      )}
                      {servedViolates ? (
                        <StatusBadge
                          tone="warning"
                          labelKey="settings.clamped.badge"
                          explanation={t("settings.clamped.body", {
                            value: effective,
                          })}
                        />
                      ) : null}
                      <Text size="xs" c="dimmed">
                        {t(item.apply_note_key)}
                      </Text>
                      <Group gap="md" align="flex-end">
                        <DisplayField
                          label={t("settings.source")}
                          value={
                            <Badge
                              variant="light"
                              color={item.source === "user" ? "blue" : "gray"}
                            >
                              {t(`settings.source.${item.source}`)}
                            </Badge>
                          }
                        />
                        <DisplayField
                          label={t("settings.changedAt")}
                          value={
                            item.updated_at
                              ? showInstant(item.updated_at)
                              : undefined
                          }
                        />
                        <DisplayField
                          label={t("settings.changedBy")}
                          value={item.updated_by_account ?? undefined}
                        />
                        {canWrite?.can ? (
                          <Button
                            size="sm"
                            variant="light"
                            loading={resetAction.isSubmitting(item.key)}
                            disabled={item.source === "seed"}
                            onClick={() => onReset(item.key, t(item.label_key))}
                          >
                            {t("settings.reset")}
                          </Button>
                        ) : null}
                      </Group>
                    </Stack>
                    );
                  })}
              </Stack>
            ))
          : null}
      </Stack>
    </PageChrome>
  );
}
