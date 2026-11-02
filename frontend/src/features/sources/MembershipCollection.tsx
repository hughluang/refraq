"use client";

import { Button, Stack, Table } from "@mantine/core";
import { useNotification, useTranslate } from "@refinedev/core";
import { useCallback, useEffect, useMemo, useState } from "react";

import { RowActions } from "@/components/display/RowActions";
import { presentProblemNotification } from "@/components/feedback/presentProblemNotification";
import { presentSaveFailure } from "@/components/feedback/presentSaveFailure";
import { FormDialog } from "@/components/form/FormDialog";
import { RecordPicker } from "@/components/form/RecordPicker";
import {
  roleRecordAdapter,
  userGroupRecordAdapter,
  userRecordAdapter,
} from "@/components/form/recordPickerAdapters";
import { SelectField } from "@/components/form/SelectField";
import { TextField } from "@/components/form/TextField";
import { useConsoleForm } from "@/components/form/useConsoleForm";
import {
  MEMBERSHIP_SUBJECT_KINDS,
  SOURCE_ACCESS_LEVELS,
  isMembershipSubjectKind,
  membershipKindLabel,
  membershipLevelLabel,
  membershipSubjectLabel,
  type MembershipSubjectKind,
  type MembershipWrite,
  type SourceAccessLevel,
  type SourceMembership,
} from "@/features/sources/membership";
export type MembershipClient = {
  list: () => Promise<{ items: SourceMembership[] }>;
  create: (body: MembershipWrite) => Promise<{ membership: SourceMembership }>;
  change: (membershipId: string, level: string) => Promise<{ membership: SourceMembership }>;
  remove: (membershipId: string) => Promise<void>;
};

type Draft = {
  subjectType: MembershipSubjectKind;
  subjectId: string;
  level: SourceAccessLevel | "";
};

const EMPTY_DRAFT: Draft = { subjectType: "user", subjectId: "", level: "viewer" };

type Props = {
  client: MembershipClient;
  editable: boolean;
};

export function MembershipCollection({ client, editable }: Props) {
  const t = useTranslate();
  const { open } = useNotification();
  const [items, setItems] = useState<SourceMembership[]>([]);
  const [loading, setLoading] = useState(true);
  const [failed, setFailed] = useState(false);
  const [attempt, setAttempt] = useState(0);
  const [creating, setCreating] = useState(false);
  const [editing, setEditing] = useState<SourceMembership | null>(null);
  const form = useConsoleForm<Draft>({
    initialValues: EMPTY_DRAFT,
    validate: {
      subjectId: (value) => (value.trim() ? null : t("sources.validation.required")),
      level: (value) => (value ? null : t("sources.validation.required")),
    },
  });

  const adapters = useMemo(
    () => ({
      user: userRecordAdapter(),
      group: userGroupRecordAdapter(),
      role: roleRecordAdapter(),
    }),
    [],
  );

  const reload = useCallback(async () => {
    const page = await client.list();
    setItems(page.items);
  }, [client]);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setFailed(false);
    void client
      .list()
      .then((page) => {
        if (cancelled) return;
        setItems(page.items);
        setFailed(false);
      })
      .catch((err: unknown) => {
        if (cancelled) return;
        setFailed(true);
        presentProblemNotification(t, err, { onRetry: () => setAttempt((value) => value + 1) });
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [attempt, client, editable, t]);

  function closeForm() {
    setCreating(false);
    setEditing(null);
    form.reset();
  }

  function openCreate() {
    form.setValues(EMPTY_DRAFT);
    form.markSaved();
    setEditing(null);
    setCreating(true);
  }

  function openChange(row: SourceMembership) {
    form.setValues({
      subjectType: isMembershipSubjectKind(row.subject.type) ? row.subject.type : "user",
      subjectId: row.subject.id,
      level: (SOURCE_ACCESS_LEVELS as readonly string[]).includes(row.level)
        ? (row.level as SourceAccessLevel)
        : "",
    });
    form.markSaved();
    setCreating(false);
    setEditing(row);
  }

  async function submit(values: Draft) {
    if (!values.level) return;
    try {
      if (editing) {
        await client.change(editing.id, values.level);
      } else {
        await client.create({
          subject: { type: values.subjectType, id: values.subjectId },
          level: values.level,
        });
      }
      form.markSaved();
      closeForm();
      open?.({ type: "success", message: t("sources.membership.saved") });
      await reload();
    } catch (err) {
      presentSaveFailure(t, err, form.applyApiError);
    }
  }

  const kindOptions = MEMBERSHIP_SUBJECT_KINDS.map((value) => ({
    value,
    label: membershipKindLabel(t, value),
  }));
  const levelOptions = SOURCE_ACCESS_LEVELS.map((value) => ({
    value,
    label: membershipLevelLabel(t, value),
  }));
  const formOpen = creating || editing != null;
  const subjectLocked = editing != null;

  return (
    <Stack gap="sm">
      {editable ? (
        <Button type="button" size="sm" onClick={openCreate}>
          {t("sources.membership.add")}
        </Button>
      ) : null}
      <Table>
        <Table.Thead>
          <Table.Tr>
            <Table.Th>{t("sources.membership.subject")}</Table.Th>
            <Table.Th>{t("sources.membership.subjectKind")}</Table.Th>
            <Table.Th>{t("sources.membership.level")}</Table.Th>
            {editable ? <Table.Th>{t("sources.fields.actions")}</Table.Th> : null}
          </Table.Tr>
        </Table.Thead>
        <Table.Tbody>
          {items.map((row) => (
            <Table.Tr key={row.id}>
              <Table.Td>{membershipSubjectLabel(t, row.subject)}</Table.Td>
              <Table.Td>{membershipKindLabel(t, row.subject.type)}</Table.Td>
              <Table.Td>{membershipLevelLabel(t, row.level)}</Table.Td>
              {editable ? (
                <Table.Td>
                  <RowActions
                    recordName={membershipSubjectLabel(t, row.subject)}
                    verbs={[
                      {
                        key: "change",
                        label: t("sources.membership.change"),
                        hidden: row.subject.missing,
                        safety: "immediate",
                        onClick: () => openChange(row),
                      },
                      {
                        key: "remove",
                        label: t("sources.membership.remove"),
                        color: "red",
                        action: {
                          safety: "confirm",
                          recordName: membershipSubjectLabel(t, row.subject),
                          title: t("sources.membership.removeTitle"),
                          consequence: t("sources.membership.removeBody"),
                          confirmLabel: t("sources.membership.remove"),
                          confirmColor: "red",
                          outcome: t("sources.membership.removed"),
                          execute: () => client.remove(row.id),
                          onSuccess: () => reload(),
                        },
                      },
                    ]}
                  />
                </Table.Td>
              ) : null}
            </Table.Tr>
          ))}
        </Table.Tbody>
      </Table>
      {!loading && !failed && items.length === 0 ? (
        <span>{t("sources.membership.empty")}</span>
      ) : null}
      <FormDialog
        opened={formOpen}
        onClose={closeForm}
        title={editing ? t("sources.membership.change") : t("sources.membership.add")}
        dirty={form.dirty}
        submitting={form.submitting}
        submitLabel={editing ? t("sources.membership.change") : t("sources.membership.add")}
        onSubmit={() => void form.submit(submit)}
      >
        <Stack gap="sm">
          <SelectField
            label={t("sources.membership.subjectKind")}
            data={kindOptions}
            editable={!subjectLocked}
            {...form.fieldProps("subjectType")}
            onChange={(value) => {
              const next = isMembershipSubjectKind(value ?? "") ? value : "user";
              form.setFieldValue("subjectType", next as MembershipSubjectKind);
              if (!subjectLocked) form.setFieldValue("subjectId", "");
            }}
          />
          {subjectLocked ? (
            <TextField
              label={t("sources.membership.subject")}
              editable={false}
              value={editing ? membershipSubjectLabel(t, editing.subject) : ""}
              onChange={() => {}}
            />
          ) : (
            <RecordPicker
              label={t("sources.membership.subject")}
              editable
              required
              adapter={adapters[form.values.subjectType]}
              value={form.values.subjectId}
              error={form.errors.subjectId}
              onChange={(value) => form.setFieldValue("subjectId", value ?? "")}
            />
          )}
          <SelectField
            label={t("sources.membership.level")}
            data={levelOptions}
            editable
            required
            {...form.fieldProps("level")}
          />
        </Stack>
      </FormDialog>
    </Stack>
  );
}
