"use client";

import {
  Button,
  Group,
  NumberInput,
  Stack,
  Text,
} from "@mantine/core";
import {
  useCan,
  useNotification,
  useTranslate,
} from "@refinedev/core";
import { useCallback, useEffect, useState } from "react";

import { DisplayField } from "@/components/display/DisplayField";
import { PageError } from "@/components/feedback/PageError";
import { PageBodySkeleton } from "@/components/feedback/PageBodySkeleton";
import { PageChrome } from "@/components/layout/PageChrome";
import { ModuleAction, ModuleId } from "@/features/console/module-identity";
import {
  clearPlatformSettingsOverride,
  fetchPlatformSettings,
  patchPlatformSettings,
} from "@/features/settings/api";
import type { PlatformSettings } from "@/features/settings/types";
import { ApiError } from "@/lib/api";

export function SettingsPanel() {
  const t = useTranslate();
  const { open } = useNotification();
  const { data: canWrite } = useCan({
    resource: ModuleId.settings,
    action: ModuleAction.edit,
  });
  const [settings, setSettings] = useState<PlatformSettings | null>(null);
  const [ttl, setTtl] = useState<number | string>(8);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [clearing, setClearing] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const data = await fetchPlatformSettings();
      setSettings(data);
      setTtl(data.admin_session_ttl_hours);
    } catch (err) {
      setSettings(null);
      setError(
        err instanceof ApiError ? err.detail : t("common.error.loadFailed"),
      );
    } finally {
      setLoading(false);
    }
  }, [t]);

  useEffect(() => {
    void load();
  }, [load]);

  async function onSave() {
    const value = typeof ttl === "number" ? ttl : Number(ttl);
    if (!Number.isInteger(value) || value < 1 || value > 168) {
      open?.({
        type: "error",
        message: t("settings.title"),
        description: t("settings.validation.ttl"),
      });
      return;
    }
    setSaving(true);
    try {
      const data = await patchPlatformSettings(value);
      setSettings(data);
      setTtl(data.admin_session_ttl_hours);
      open?.({
        type: "success",
        message: t("settings.title"),
        description: t("settings.save.success"),
      });
    } catch (err) {
      open?.({
        type: "error",
        message: t("settings.title"),
        description:
          err instanceof ApiError ? err.detail : t("common.error"),
      });
    } finally {
      setSaving(false);
    }
  }

  async function onClear() {
    setClearing(true);
    try {
      const data = await clearPlatformSettingsOverride();
      setSettings(data);
      setTtl(data.admin_session_ttl_hours);
      open?.({
        type: "success",
        message: t("settings.title"),
        description: t("settings.clear.success"),
      });
    } catch (err) {
      open?.({
        type: "error",
        message: t("settings.title"),
        description:
          err instanceof ApiError ? err.detail : t("common.error"),
      });
    } finally {
      setClearing(false);
    }
  }

  return (
    <PageChrome
      title={t("settings.title")}
      description={t("settings.description")}
    >
      <Stack gap="md">
        {loading ? <PageBodySkeleton rows={4} /> : null}
        {!loading && error ? (
          <PageError message={error} onRetry={() => void load()} />
        ) : null}
        {!loading && !error && settings ? (
          <>
            <NumberInput
              label={t("settings.fields.ttl")}
              description={t("settings.fields.ttl.hint")}
              value={ttl}
              onChange={setTtl}
              min={1}
              max={168}
              allowDecimal={false}
              disabled={!canWrite?.can}
            />
            {canWrite?.can ? (
              <Stack gap="xs">
                <Group gap="sm">
                  <Button loading={saving} onClick={() => void onSave()}>
                    {t("settings.save")}
                  </Button>
                  <Button
                    variant="light"
                    loading={clearing}
                    disabled={
                      settings.admin_session_ttl_hours_source !== "override"
                    }
                    onClick={() => void onClear()}
                  >
                    {t("settings.clearOverride")}
                  </Button>
                </Group>
                <Text size="xs" c="dimmed">
                  {t("settings.hint.override")}
                </Text>
              </Stack>
            ) : null}
            <DisplayField
              label={t("settings.fields.source")}
              description={t("settings.fields.source.hint")}
              value={
                settings.admin_session_ttl_hours_source === "override"
                  ? t("settings.fields.source.override")
                  : t("settings.fields.source.env")
              }
            />
            <DisplayField
              label={t("settings.fields.default")}
              description={t("settings.fields.default.hint")}
              value={String(settings.admin_session_ttl_hours_default)}
            />
            <DisplayField
              label={t("settings.fields.env")}
              description={t("settings.fields.env.hint")}
              value={settings.refraq_env}
            />
          </>
        ) : null}
      </Stack>
    </PageChrome>
  );
}
