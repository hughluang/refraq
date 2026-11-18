"use client";

import { Button, Stack } from "@mantine/core";
import { useCan, useTranslate } from "@refinedev/core";
import { useCallback, useEffect, useState } from "react";
import { DisplayField } from "@/components/display/DisplayField";
import { Instant } from "@/components/display/Instant";
import { FormSection } from "@/components/form/FormSection";
import { FormDialog } from "@/components/form/FormDialog";
import { TextField } from "@/components/form/TextField";
import { PasswordInput } from "@/components/form/PasswordInput";
import { useConsoleForm } from "@/components/form/useConsoleForm";
import { presentProblemNotification } from "@/components/feedback/presentProblemNotification";
import { presentSaveFailure } from "@/components/feedback/presentSaveFailure";
import { useConsoleMutation } from "@/components/feedback/useConsoleMutation";
import { HeaderActions } from "@/components/layout/HeaderActions";
import { PageChrome } from "@/components/layout/PageChrome";
import { ConsoleLink } from "@/components/navigation/ConsoleLink";
import { getNotificationChannel, replaceNotificationChannel, testNotificationChannel, type NotificationChannel } from "./notification-api";

const empty = () => ({ primary: { https_url: "", credential: { header_name: "", secret: "" } }, fallback: { https_url: "", credential: { header_name: "", secret: "" } }, responder: "" });

export function NotificationChannelPanel() {
  const t = useTranslate();
  const { data: canWrite } = useCan({ resource: "settings", action: "edit" });
  const [channel, setChannel] = useState<NotificationChannel | null>(null);
  const [loading, setLoading] = useState(true);
  const [opened, setOpened] = useState(false);
  const [pending, setPending] = useState<string | null>(null);
  const mutation = useConsoleMutation();
  const form = useConsoleForm({ initialValues: empty(), validate: {
    responder: value => value.trim() ? null : t("notificationChannel.required"),
    primary: { https_url: value => value.startsWith("https://") ? null : t("notificationChannel.https"), credential: { header_name: value => value.trim() ? null : t("notificationChannel.required"), secret: value => value ? null : t("notificationChannel.required") } },
    fallback: { https_url: value => value.startsWith("https://") ? null : t("notificationChannel.https"), credential: { header_name: value => value.trim() ? null : t("notificationChannel.required"), secret: value => value ? null : t("notificationChannel.required") } },
  } });
  const load = useCallback(async () => {
    setLoading(true);
    try { setChannel((await getNotificationChannel()).channel); }
    catch (error) { setChannel(null); presentProblemNotification(t, error); }
    finally { setLoading(false); }
  }, [t]);
  useEffect(() => { void load(); }, [load]);
  async function save() {
    if (!canWrite?.can) return;
    await form.submit(async values => {
      try {
        setChannel((await replaceNotificationChannel(values)).channel);
        form.setValues(empty());
        form.resetDirty(empty());
        setOpened(false);
      } catch (error) { presentSaveFailure(t, error, form.applyApiError); }
    });
  }
  return <PageChrome title={t("notificationChannel.title")} description={t("notificationChannel.redacted")} status={loading ? "loading" : channel ? "ready" : "unloaded"} onRetry={() => void load()}
    actions={<HeaderActions navigation={<><Button component={ConsoleLink} href="/console/settings" size="sm" variant="light">{t("settings.title")}</Button><Button size="sm" variant="light" onClick={() => void load()}>{t("common.refresh")}</Button></>}
      standard={canWrite?.can && channel ? <><Button size="sm" variant="light" onClick={() => { form.setValues(empty()); form.resetDirty(empty()); setOpened(true); }}>{t("notificationChannel.replace")}</Button><Button size="sm" variant="light" loading={mutation.submitting} onClick={() => mutation.run({ safety: "immediate", recordName: t("notificationChannel.title"), outcome: t("mirrors.accepted"), execute: async () => { const operation = await testNotificationChannel(); setPending(operation.operation_id); }, onSuccess: load })}>{t("notificationChannel.test")}</Button></> : null} />}>
    {channel ? <Stack gap="lg"><FormSection title={t("notificationChannel.state")}>
      {(["configured", "primary_configured", "fallback_configured", "responder", "delivery_state", "last_fault_code"] as const).map(key => <DisplayField key={key} label={t(`notificationChannel.${key}`)} value={typeof channel[key] === "boolean" ? t(channel[key] ? "common.yes" : "common.no") : key === "delivery_state" ? JSON.stringify(channel.delivery_state, null, 2) : channel[key]} />)}
      <DisplayField label={t("notificationChannel.last_test_at")} value={<Instant value={channel.last_test_at} />} />
      <DisplayField label={t("mirrors.operation")} value={pending ? `${pending}: ${t("mirrors.pending")}` : null} helper={t("notificationChannel.pendingHelp")} />
    </FormSection></Stack> : null}
    <FormDialog opened={opened && Boolean(canWrite?.can)} onClose={() => { form.setValues(empty()); form.resetDirty(empty()); setOpened(false); }} title={t("notificationChannel.replace")} dirty={opened && form.dirty} submitting={form.submitting} submitLabel={t("notificationChannel.replace")} onSubmit={() => void save()}>
      <Stack gap="md"><TextField editable label={t("notificationChannel.responder")} required {...form.fieldProps("responder")} />
        {(["primary", "fallback"] as const).map(route => <FormSection key={route} title={t(`notificationChannel.${route}`)} columns={1} description={t("notificationChannel.replaceHelp")}>
          <TextField editable label={t("notificationChannel.url")} required {...form.fieldProps(`${route}.https_url`)} />
          <TextField editable label={t("notificationChannel.header")} required {...form.fieldProps(`${route}.credential.header_name`)} />
          <PasswordInput label={t("notificationChannel.secret")} required autoComplete="new-password" {...form.fieldProps(`${route}.credential.secret`)} />
        </FormSection>)}
      </Stack>
    </FormDialog>{mutation.dialog}
  </PageChrome>;
}
