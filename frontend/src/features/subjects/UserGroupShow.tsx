"use client";

import { Button, Group, Select, Stack, Table, Text, Title } from "@mantine/core";
import { useCan, useNotification, useTranslate } from "@refinedev/core";
import Link from "next/link";
import { useCallback, useEffect, useState } from "react";

import { ListTable } from "@/components/display/ListTable";
import { PageError } from "@/components/feedback/PageError";
import { PageBodySkeleton } from "@/components/feedback/PageBodySkeleton";
import { TextField } from "@/components/form/TextField";
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
import { listUsers } from "@/features/users/api";
import type { UserRow } from "@/features/users/types";
import { useConsolePagedList } from "@/hooks/useConsolePagedList";
import { ApiError } from "@/lib/api";
import type { PageQuery } from "@/lib/pagination";

const PAGE_SIZE = 50;

type Props = { groupId: string };

export function UserGroupShow({ groupId }: Props) {
  const t = useTranslate();
  const { open } = useNotification();
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
  const [users, setUsers] = useState<UserRow[]>([]);
  const [memberId, setMemberId] = useState<string | null>(null);
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
      description: err instanceof ApiError ? err.detail : t("common.error.loadFailed"),
    });
  }

  useEffect(() => {
    let cancelled = false;
    void (async () => {
      setLoading(true);
      try {
        const [loaded, values, defs, people] = await Promise.all([
          getUserGroup(groupId),
          getGroupSubjectValues(groupId),
          listAllSubjectAttributes(),
          listUsers({ limit: 200, offset: 0 }).then((page) => page.items),
        ]);
        if (cancelled) return;
        setGroup(loaded.group);
        setName(loaded.group.name);
        setDescription(loaded.group.description ?? "");
        setDefinitions(defs);
        setUsers(people);
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

  async function addMember() {
    if (!memberId) return;
    setBusy(true);
    try {
      await addGroupMember(groupId, memberId);
      setMemberId(null);
      await members.reload();
      const loaded = await getUserGroup(groupId);
      setGroup(loaded.group);
    } catch (err) {
      notifyError(err);
    } finally {
      setBusy(false);
    }
  }

  async function removeMember(userId: string) {
    setBusy(true);
    try {
      await removeGroupMember(groupId, userId);
      await members.reload();
      const loaded = await getUserGroup(groupId);
      setGroup(loaded.group);
    } catch (err) {
      notifyError(err);
    } finally {
      setBusy(false);
    }
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
        <Button component={Link} href="/console/user-groups" size="sm" variant="default">
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
              <Select
                label={t("userGroups.members.add")}
                data={users.map((user) => ({
                  value: user.id,
                  label: user.account,
                }))}
                value={memberId}
                onChange={setMemberId}
                searchable
                clearable
              />
              <Button size="sm" disabled={!memberId} loading={busy} onClick={() => void addMember()}>
                {t("userGroups.members.add")}
              </Button>
            </Group>
          ) : null}
          <ListTable
            list={members}
            columnCount={editable ? 3 : 2}
            head={
              <Table.Tr>
                <Table.Th>{t("users.fields.account")}</Table.Th>
                <Table.Th>{t("users.fields.displayName")}</Table.Th>
                {editable ? <Table.Th>{t("userGroups.fields.actions")}</Table.Th> : null}
              </Table.Tr>
            }
          >
            {members.items.map((member) => (
              <Table.Tr key={member.id}>
                <Table.Td>{member.account}</Table.Td>
                <Table.Td>{member.display_name}</Table.Td>
                {editable ? (
                  <Table.Td>
                    <Button
                      size="xs"
                      variant="light"
                      color="red"
                      onClick={() => void removeMember(member.id)}
                    >
                      {t("userGroups.members.remove")}
                    </Button>
                  </Table.Td>
                ) : null}
              </Table.Tr>
            ))}
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
            users={users}
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
