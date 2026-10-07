"use client";

import { Button, Group, MultiSelect, Stack, Text, Title } from "@mantine/core";
import { useCan, useNotification, useTranslate } from "@refinedev/core";
import Link from "next/link";
import { useEffect, useState } from "react";

import { PageError } from "@/components/feedback/PageError";
import { PageBodySkeleton } from "@/components/feedback/PageBodySkeleton";
import { FieldDisplay } from "@/components/form/FieldDisplay";
import { PageChrome } from "@/components/layout/PageChrome";
import { ModuleAction, ModuleId } from "@/features/console/module-identity";
import {
  getUser,
  getUserGroups,
  getUserSubjectValues,
  listAllSubjectAttributes,
  listUserGroups,
  putUserGroups,
  putUserSubjectValues,
} from "@/features/subjects/api";
import { encodeSubjectDrafts } from "@/features/subjects/rules";
import {
  formatSubjectValues,
  SubjectValuesEditor,
} from "@/features/subjects/SubjectValuesEditor";
import type { SubjectAttribute, SubjectValues, UserGroup } from "@/features/subjects/types";
import { listUsers } from "@/features/users/api";
import type { UserRow } from "@/features/users/types";
import { ApiError } from "@/lib/api";

type Props = { userId: string };

export function UserShow({ userId }: Props) {
  const t = useTranslate();
  const { open } = useNotification();
  const { data: canWrite } = useCan({
    resource: ModuleId.users,
    action: ModuleAction.edit,
  });
  const editable = Boolean(canWrite?.can);
  const [user, setUser] = useState<UserRow | null>(null);
  const [groups, setGroups] = useState<UserGroup[]>([]);
  const [groupIds, setGroupIds] = useState<string[]>([]);
  const [definitions, setDefinitions] = useState<SubjectAttribute[]>([]);
  const [drafts, setDrafts] = useState<Record<string, string[]>>({});
  const [effective, setEffective] = useState<SubjectValues>({});
  const [people, setPeople] = useState<UserRow[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);

  function notifyError(err: unknown) {
    open?.({
      type: "error",
      message: t("users.title"),
      description: err instanceof ApiError ? err.detail : t("common.error.loadFailed"),
    });
  }

  useEffect(() => {
    let cancelled = false;
    void (async () => {
      setLoading(true);
      try {
        const [loaded, membership, values, defs, catalog, users] = await Promise.all([
          getUser(userId),
          getUserGroups(userId),
          getUserSubjectValues(userId),
          listAllSubjectAttributes(),
          listUserGroups({ limit: 200, offset: 0 }),
          listUsers({ limit: 200, offset: 0 }),
        ]);
        if (cancelled) return;
        setUser(loaded.user);
        setGroups(catalog.items);
        setGroupIds(membership.groups.map((group) => group.id));
        setDefinitions(defs);
        setPeople(users.items);
        setEffective(values.effective);
        const next: Record<string, string[]> = {};
        for (const item of defs) {
          next[item.key] = (values.values[item.key] ?? []).map(String);
        }
        setDrafts(next);
        setError(null);
      } catch (err) {
        if (!cancelled) {
          setError(err instanceof ApiError ? err.detail : t("common.error.loadFailed"));
        }
      } finally {
        if (!cancelled) setLoading(false);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [t, userId]);

  async function saveGroups() {
    setBusy(true);
    try {
      const saved = await putUserGroups(userId, groupIds);
      setGroupIds(saved.groups.map((group) => group.id));
      const values = await getUserSubjectValues(userId);
      setEffective(values.effective);
    } catch (err) {
      notifyError(err);
    } finally {
      setBusy(false);
    }
  }

  async function saveValues() {
    const encoded = encodeSubjectDrafts(
      definitions.map((item) => ({
        key: item.key,
        valueType: item.value_type,
        multiValue: item.multi_value,
        texts: drafts[item.key] ?? [],
      })),
    );
    if (!encoded.ok) {
      open?.({
        type: "error",
        message: t("subjectAttributes.title"),
        description: t(`subjectAttributes.values.error.${encoded.issue.reason}`, {
          key: encoded.issue.key,
        }),
      });
      return;
    }
    setBusy(true);
    try {
      const saved = await putUserSubjectValues(userId, encoded.values);
      const next: Record<string, string[]> = {};
      for (const item of definitions) {
        next[item.key] = (saved.values[item.key] ?? []).map(String);
      }
      setDrafts(next);
      setEffective(saved.effective);
    } catch (err) {
      notifyError(err);
    } finally {
      setBusy(false);
    }
  }

  if (loading) {
    return (
      <PageChrome title={t("users.title")}>
        <PageBodySkeleton />
      </PageChrome>
    );
  }
  if (error || !user) {
    return (
      <PageChrome title={t("users.title")}>
        <PageError
          message={error ?? t("common.error.loadFailed")}
          onRetry={() => location.reload()}
        />
      </PageChrome>
    );
  }

  const groupOptions = groups.map((group) => ({
    value: group.id,
    label: group.name,
  }));

  return (
    <PageChrome
      title={user.display_name}
      description={user.account}
      actions={
        <Button component={Link} href="/console/users" size="sm" variant="default">
          {t("users.back")}
        </Button>
      }
    >
      <Stack gap="lg">
        <FieldDisplay label={t("users.fields.status")} value={t(`users.status.${user.status}`)} />
        <Stack gap="sm">
          <Title order={4}>{t("users.groups.title")}</Title>
          {editable ? (
            <MultiSelect
              label={t("users.groups.title")}
              data={groupOptions}
              value={groupIds}
              onChange={setGroupIds}
              searchable
            />
          ) : (
            <FieldDisplay
              label={t("users.groups.title")}
              value={groupIds
                .map((id) => groupOptions.find((option) => option.value === id)?.label ?? id)
                .join(", ")}
            />
          )}
          {editable ? (
            <Group>
              <Button size="sm" loading={busy} onClick={() => void saveGroups()}>
                {t("users.groups.save")}
              </Button>
            </Group>
          ) : null}
        </Stack>
        <Stack gap="sm">
          <Title order={4}>{t("subjectAttributes.values.title")}</Title>
          <SubjectValuesEditor
            definitions={definitions}
            drafts={drafts}
            users={people}
            editable={editable}
            onChange={(key, texts) =>
              setDrafts((current) => ({ ...current, [key]: texts }))
            }
          />
          {editable && definitions.length > 0 ? (
            <Group>
              <Button size="sm" loading={busy} onClick={() => void saveValues()}>
                {t("subjectAttributes.values.save")}
              </Button>
            </Group>
          ) : null}
          <Text size="sm" c="dimmed">
            {t("subjectAttributes.values.effective")}
          </Text>
          <FieldDisplay
            label={t("subjectAttributes.values.effective")}
            value={formatSubjectValues(effective) || t("subjectAttributes.values.none")}
          />
        </Stack>
      </Stack>
    </PageChrome>
  );
}
