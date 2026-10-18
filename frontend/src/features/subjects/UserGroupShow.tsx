"use client";

import { Button, Group, Stack, Table, Text, Title } from "@mantine/core";
import { useCan, useNotification, useTranslate } from "@refinedev/core";
import { ConsoleLink } from "@/components/navigation/ConsoleLink";
import { useCallback, useEffect, useState } from "react";

import { ListTable } from "@/components/display/ListTable";
import { RecordReference } from "@/components/display/RecordReference";
import { RowActions } from "@/components/display/RowActions";
import { PageError } from "@/components/feedback/PageError";
import { PageBodySkeleton } from "@/components/feedback/PageBodySkeleton";
import { useConsoleMutation } from "@/components/feedback/useConsoleMutation";
import { TextField } from "@/components/form/TextField";
import { RecordPicker } from "@/components/form/RecordPicker";
import { userRecordAdapter, type RecordOption } from "@/components/form/recordPickerAdapters";
import { PageChrome } from "@/components/layout/PageChrome";
import { ModuleAction, ModuleId } from "@/features/console/module-identity";
import {
  addGroupMember,
  getGroupSubjectValues,
  getUserGroup,
  listGroupMembers,
  listAllSubjectAttributes,
  patchUserGroup,
  putGroupSubjectValues,
  removeGroupMember,
} from "@/features/subjects/api";
import {
  encodeSubjectDrafts,
  subjectNameError,
} from "@/features/subjects/rules";
import { SubjectValuesEditor } from "@/features/subjects/SubjectValuesEditor";
import type { SubjectAttribute, UserGroup } from "@/features/subjects/types";
import type { UserRow } from "@/features/users/types";
import { useConsolePagedList } from "@/hooks/useConsolePagedList";
import { problemMessage } from "@/lib/problem";
import type { PageQuery } from "@/lib/pagination";

const PAGE_SIZE = 50;

type Props = { groupId: string };

export function UserGroupShow({ groupId }: Props) {
  const t = useTranslate();
  const { open } = useNotification();
  const membership = useConsoleMutation();
  const { data: canWrite } = useCan({
    resource: ModuleId.userGroups,
    action: ModuleAction.edit,
  });
  const editable = Boolean(canWrite?.can);
  const [group, setGroup] = useState<UserGroup | null>(null);
  const [name, setName] = useState("");
  const [description, setDescription] = useState("");
  const [definitions, setDefinitions] = useState<SubjectAttribute[]>([]);
  const [drafts, setDrafts] = useState<Record<string, string[]>>({});
  const [member, setMember] = useState<RecordOption | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);

  const fetchMembers = useCallback(
    (query: PageQuery) => listGroupMembers(groupId, query),
    [groupId],
  );
  const members = useConsolePagedList<UserRow>({
    pageSize: PAGE_SIZE,
    fetch: fetchMembers,
    enabled: group != null,
    initialLoading: false,
  });

  function notifyError(err: unknown) {
    open?.({
      type: "error",
      message: t("userGroups.title"),
      description: problemMessage(t, err, t("common.error.loadFailed")),
    });
  }

  useEffect(() => {
    let cancelled = false;
    void (async () => {
      setLoading(true);
      try {
        const [loaded, values, defs] = await Promise.all([
          getUserGroup(groupId),
          getGroupSubjectValues(groupId),
          listAllSubjectAttributes(),
        ]);
        if (cancelled) return;
        setGroup(loaded.group);
        setName(loaded.group.name);
        setDescription(loaded.group.description ?? "");
        setDefinitions(defs);
        const next: Record<string, string[]> = {};
        for (const item of defs) {
          next[item.key] = (values.values[item.key] ?? []).map(String);
        }
        setDrafts(next);
        setError(null);
      } catch (err) {
        if (!cancelled) {
          setError(problemMessage(t, err, t("common.error.loadFailed")));
        }
      } finally {
        if (!cancelled) setLoading(false);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [groupId, t]);

  async function saveGroup() {
    if (!group || subjectNameError(name)) return;
    setBusy(true);
    try {
      const updated = await patchUserGroup(group.id, {
        name: name.trim(),
        description: description.trim() || null,
      });
      setGroup(updated.group);
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
      const saved = await putGroupSubjectValues(groupId, encoded.values);
      const next: Record<string, string[]> = {};
      for (const item of definitions) {
        next[item.key] = (saved.values[item.key] ?? []).map(String);
      }
      setDrafts(next);
    } catch (err) {
      notifyError(err);
    } finally {
      setBusy(false);
    }
  }

  async function refreshGroup() {
    await members.reload();
    const loaded = await getUserGroup(groupId);
    setGroup(loaded.group);
  }

  function addMember() {
    if (!member) return;
    const userId = member.id;
    const recordName = member.name || userId;
    membership.run({
      safety: "undoable",
      key: "add",
      recordName,
      outcome: t("userGroups.members.added"),
      execute: async () => {
        setBusy(true);
        try {
          await addGroupMember(groupId, userId);
          setMember(null);
          await refreshGroup();
        } finally {
          setBusy(false);
        }
      },
      undo: async () => {
        await removeGroupMember(groupId, userId);
        await refreshGroup();
      },
    });
  }

  if (loading) {
    return (
      <PageChrome title={t("userGroups.title")}>
        <PageBodySkeleton />
      </PageChrome>
    );
  }
  if (error || !group) {
    return (
      <PageChrome title={t("userGroups.title")}>
        <PageError message={error ?? t("common.error.loadFailed")} onRetry={() => location.reload()} />
      </PageChrome>
    );
  }

  const nameIssue = subjectNameError(name);

  return (
    <PageChrome
      title={group.name}
      description={group.key}
      actions={
        <Button component={ConsoleLink} href="/console/user-groups" size="sm" variant="default">
          {t("userGroups.back")}
        </Button>
      }
    >
      <Stack gap="lg">
        <Stack gap="sm">
          <TextField editable={false} label={t("userGroups.fields.key")} value={group.key} />
          <TextField
            editable={editable}
            required
            label={t("userGroups.fields.name")}
            value={name}
            onChange={(event) => setName(event.currentTarget.value)}
            error={nameIssue ? t(`userGroups.validation.name.${nameIssue}`) : undefined}
          />
          <TextField
            editable={editable}
            label={t("userGroups.fields.description")}
            value={description}
            onChange={(event) => setDescription(event.currentTarget.value)}
          />
          {editable ? (
            <Group>
              <Button
                size="sm"
                loading={busy}
                disabled={Boolean(nameIssue)}
                onClick={() => void saveGroup()}
              >
                {t("userGroups.save")}
              </Button>
            </Group>
          ) : null}
        </Stack>
        <Stack gap="sm">
          <Title order={4}>{t("userGroups.members.title")}</Title>
          {editable ? (
            <Group align="flex-end">
              <RecordPicker
                label={t("userGroups.members.add")}
                adapter={userRecordAdapter()}
                value={member?.id ?? null}
                editable
                clearable
                onChange={(id, option) => setMember(id && option ? option : null)}
              />
              <Button
                size="sm"
                disabled={!member}
                loading={busy || membership.isSubmitting("add")}
                onClick={addMember}
              >
                {t("userGroups.members.add")}
              </Button>
            </Group>
          ) : null}
          <ListTable
            embedded
            list={members}
            columnCount={editable ? 2 : 1}
            minWidth={520}
            head={
              <Table.Tr>
                <Table.Th>{t("users.fields.displayName")}</Table.Th>
                {editable ? <Table.Th>{t("userGroups.fields.actions")}</Table.Th> : null}
              </Table.Tr>
            }
          >
            {members.items.map((member) => {
              const recordName = member.display_name || member.account;
              return (
                <Table.Tr key={member.id}>
                  <Table.Td>
                    <RecordReference
                      name={recordName}
                      recordKey={member.account}
                      href={`/console/users/${member.id}`}
                    />
                  </Table.Td>
                  {editable ? (
                    <Table.Td>
                      <RowActions
                        recordName={recordName}
                        verbs={[
                          {
                            key: member.id,
                            label: t("userGroups.members.remove"),
                            color: "red",
                            action: {
                              safety: "undoable",
                              recordName,
                              outcome: t("userGroups.members.removed"),
                              execute: async () => {
                                await removeGroupMember(groupId, member.id);
                                await refreshGroup();
                              },
                              undo: async () => {
                                await addGroupMember(groupId, member.id);
                                await refreshGroup();
                              },
                            },
                          },
                        ]}
                      />
                    </Table.Td>
                  ) : null}
                </Table.Tr>
              );
            })}
          </ListTable>
        </Stack>
        <Stack gap="sm">
          <Title order={4}>{t("subjectAttributes.values.title")}</Title>
          <Text size="sm" c="dimmed">
            {t("subjectAttributes.values.groupHint")}
          </Text>
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
        </Stack>
      </Stack>
    </PageChrome>
  );
}
