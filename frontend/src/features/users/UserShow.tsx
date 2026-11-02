"use client";

import { Button, Group, Stack, Table, Text, Title } from "@mantine/core";
import { useCan, useNotification, useTranslate } from "@refinedev/core";
import { useCallback, useEffect, useRef, useState } from "react";

import { presentProblemNotification } from "@/components/feedback/presentProblemNotification";
import { FieldDisplay } from "@/components/form/FieldDisplay";
import { RecordMultiPicker } from "@/components/form/RecordPicker";
import { userGroupRecordAdapter } from "@/components/form/recordPickerAdapters";
import { PageChrome } from "@/components/layout/PageChrome";
import { ConsoleLink } from "@/components/navigation/ConsoleLink";
import { ModuleAction, ModuleId } from "@/features/console/module-identity";
import {
  contributionPath,
  membershipLevelLabel,
  type UserSourceAccessItem,
} from "@/features/sources/membership";
import {
  getUser,
  getUserGroups,
  getUserSourceAccess,
  getUserSubjectValues,
  listAllSubjectAttributes,
  putUserGroups,
  putUserSubjectValues,
} from "@/features/subjects/api";
import { encodeSubjectDrafts } from "@/features/subjects/rules";
import {
  formatSubjectValues,
  SubjectValuesEditor,
} from "@/features/subjects/SubjectValuesEditor";
import type { SubjectAttribute, SubjectValues } from "@/features/subjects/types";
import type { UserRow } from "@/features/users/types";
import { problemMessage } from "@/lib/problem";

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
  const [groupIds, setGroupIds] = useState<string[]>([]);
  const [definitions, setDefinitions] = useState<SubjectAttribute[]>([]);
  const [drafts, setDrafts] = useState<Record<string, string[]>>({});
  const [effective, setEffective] = useState<SubjectValues>({});
  const [sourceAccess, setSourceAccess] = useState<UserSourceAccessItem[]>([]);
  const [failure, setFailure] = useState(false);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const generation = useRef(0);
  const loadRef = useRef<() => Promise<void>>(async () => {});

  function notifyError(err: unknown) {
    open?.({
      type: "error",
      message: t("users.title"),
      description: problemMessage(t, err, t("common.error.loadFailed")),
    });
  }

  const load = useCallback(async () => {
    const current = ++generation.current;
    setLoading(true);
    setFailure(false);
    try {
      const [loaded, membership, values, defs, access] = await Promise.all([
        getUser(userId),
        getUserGroups(userId),
        getUserSubjectValues(userId),
        listAllSubjectAttributes(),
        getUserSourceAccess(userId),
      ]);
      if (current !== generation.current) return;
      setUser(loaded.user);
      setGroupIds(membership.groups.map((group) => group.id));
      setDefinitions(defs);
      setEffective(values.effective);
      setSourceAccess(access.items);
      const next: Record<string, string[]> = {};
      for (const item of defs) {
        next[item.key] = (values.values[item.key] ?? []).map(String);
      }
      setDrafts(next);
    } catch (err) {
      if (current !== generation.current) return;
      setUser(null);
      setFailure(true);
      presentProblemNotification(t, err, { onRetry: () => void loadRef.current() });
    } finally {
      if (current === generation.current) setLoading(false);
    }
  }, [t, userId]);

  loadRef.current = load;

  useEffect(() => {
    void load();
    return () => {
      generation.current += 1;
    };
  }, [load]);

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
    return <PageChrome title={t("users.title")} status="loading" />;
  }
  if (failure) {
    return (
      <PageChrome
        title={t("users.title")}
        status="unloaded"
        onRetry={() => void loadRef.current()}
      />
    );
  }
  if (!user) {
    return <PageChrome title={t("users.title")} status="notFound" />;
  }

  return (
    <PageChrome
      title={t("users.title")}
      recordTitle={user.display_name}
      description={user.account}
      recent={{ moduleId: "users", title: user.display_name }}
      actions={
        <Button component={ConsoleLink} href="/console/users" size="sm" variant="default">
          {t("users.back")}
        </Button>
      }
    >
      <Stack gap="lg">
        <FieldDisplay label={t("users.fields.status")} value={t(`users.status.${user.status}`)} />
        <Stack gap="sm">
          <Title order={4}>{t("users.groups.title")}</Title>
          <RecordMultiPicker
            editable={editable}
            label={t("users.groups.title")}
            adapter={userGroupRecordAdapter()}
            value={groupIds}
            onChange={setGroupIds}
          />
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
        <Stack gap="sm">
          <Title order={4}>{t("sources.membership.userAccess")}</Title>
          {sourceAccess.length === 0 ? (
            <Text size="sm">{t("sources.membership.userAccess.empty")}</Text>
          ) : (
            <Table>
              <Table.Thead>
                <Table.Tr>
                  <Table.Th>{t("sources.membership.userAccess.source")}</Table.Th>
                  <Table.Th>{t("sources.membership.level")}</Table.Th>
                  <Table.Th>{t("sources.membership.userAccess.path")}</Table.Th>
                </Table.Tr>
              </Table.Thead>
              <Table.Tbody>
                {sourceAccess.map((item) => (
                  <Table.Tr key={item.source_id}>
                    <Table.Td>
                      {item.name}
                      <Text span c="dimmed" size="sm">
                        {" "}
                        {item.key}
                      </Text>
                    </Table.Td>
                    <Table.Td>{membershipLevelLabel(t, item.level)}</Table.Td>
                    <Table.Td>{contributionPath(t, item.contributions)}</Table.Td>
                  </Table.Tr>
                ))}
              </Table.Tbody>
            </Table>
          )}
        </Stack>
      </Stack>
    </PageChrome>
  );
}
