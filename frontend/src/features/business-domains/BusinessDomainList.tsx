"use client";

import {
  Button,
  Group,
  Modal,
  Stack,
  Table,
  Text,
  TextInput,
  Textarea,
} from "@mantine/core";
import { useForm } from "@mantine/form";
import {
  CanAccess,
  useCan,
  useNotification,
  useTranslate,
} from "@refinedev/core";
import { useCallback, useEffect, useState } from "react";

import { EmptyState } from "@/components/feedback/EmptyState";
import { PageError } from "@/components/feedback/PageError";
import { PageLoader } from "@/components/feedback/PageLoader";
import { PageChrome } from "@/components/layout/PageChrome";
import {
  createBusinessDomain,
  deleteBusinessDomain,
  listBusinessDomains,
  patchBusinessDomain,
} from "@/features/business-domains/api";
import type { BusinessDomain } from "@/features/business-domains/types";
import { ModuleAction, ModuleId } from "@/features/console/module-identity";
import { ApiError } from "@/lib/api";

type CreateForm = {
  code: string;
  name: string;
  description: string;
};

type EditForm = {
  name: string;
  description: string;
};

export function BusinessDomainList() {
  const t = useTranslate();
  const { open } = useNotification();
  const { data: canWrite } = useCan({
    resource: ModuleId.businessDomains,
    action: ModuleAction.create,
  });

  const [items, setItems] = useState<BusinessDomain[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [q, setQ] = useState("");
  const [createOpen, setCreateOpen] = useState(false);
  const [editTarget, setEditTarget] = useState<BusinessDomain | null>(null);
  const [deleteTarget, setDeleteTarget] = useState<BusinessDomain | null>(null);
  const [busy, setBusy] = useState(false);

  const createForm = useForm<CreateForm>({
    initialValues: { code: "", name: "", description: "" },
  });
  const editForm = useForm<EditForm>({
    initialValues: { name: "", description: "" },
  });

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const data = await listBusinessDomains({
        q: q.trim() || undefined,
        limit: 500,
      });
      setItems(data.items);
    } catch (err) {
      setError(err instanceof ApiError ? err.detail : String(err));
    } finally {
      setLoading(false);
    }
  }, [q]);

  useEffect(() => {
    void load();
  }, [load]);

  const submitCreate = async (values: CreateForm) => {
    setBusy(true);
    try {
      await createBusinessDomain({
        code: values.code.trim(),
        name: values.name.trim(),
        description: values.description.trim() || null,
      });
      setCreateOpen(false);
      createForm.reset();
      open?.({
        type: "success",
        message: t("businessDomains.create.success"),
      });
      await load();
    } catch (err) {
      open?.({
        type: "error",
        message: err instanceof ApiError ? err.detail : String(err),
      });
    } finally {
      setBusy(false);
    }
  };

  const submitEdit = async (values: EditForm) => {
    if (!editTarget) return;
    setBusy(true);
    try {
      await patchBusinessDomain(editTarget.id, {
        name: values.name.trim(),
        description: values.description.trim() || null,
      });
      setEditTarget(null);
      open?.({
        type: "success",
        message: t("businessDomains.update.success"),
      });
      await load();
    } catch (err) {
      open?.({
        type: "error",
        message: err instanceof ApiError ? err.detail : String(err),
      });
    } finally {
      setBusy(false);
    }
  };

  const confirmDelete = async () => {
    if (!deleteTarget) return;
    setBusy(true);
    try {
      await deleteBusinessDomain(deleteTarget.id);
      setDeleteTarget(null);
      open?.({
        type: "success",
        message: t("businessDomains.delete.success"),
      });
      await load();
    } catch (err) {
      open?.({
        type: "error",
        message: err instanceof ApiError ? err.detail : String(err),
      });
    } finally {
      setBusy(false);
    }
  };

  const createAction = (
    <CanAccess
      resource={ModuleId.businessDomains}
      action={ModuleAction.create}
    >
      <Button size="sm" onClick={() => setCreateOpen(true)}>
        {t("businessDomains.create")}
      </Button>
    </CanAccess>
  );

  if (error) {
    return (
      <PageChrome
        title={t("businessDomains.title")}
        description={t("businessDomains.description")}
      >
        <PageError message={error} onRetry={() => void load()} />
      </PageChrome>
    );
  }

  return (
    <PageChrome
      title={t("businessDomains.title")}
      description={t("businessDomains.description")}
      actions={createAction}
    >
      <Group mb="md">
        <TextInput
          placeholder={t("businessDomains.search")}
          value={q}
          onChange={(e) => setQ(e.currentTarget.value)}
          w={280}
        />
      </Group>
      {loading ? (
        <PageLoader />
      ) : items.length === 0 ? (
        <EmptyState
          action={
            canWrite?.can ? (
              <Button size="xs" onClick={() => setCreateOpen(true)}>
                {t("businessDomains.create")}
              </Button>
            ) : undefined
          }
        />
      ) : (
        <Table striped highlightOnHover>
          <Table.Thead>
            <Table.Tr>
              <Table.Th>{t("businessDomains.fields.code")}</Table.Th>
              <Table.Th>{t("businessDomains.fields.name")}</Table.Th>
              <Table.Th>{t("businessDomains.fields.description")}</Table.Th>
              <Table.Th>{t("businessDomains.fields.updatedAt")}</Table.Th>
              <Table.Th />
            </Table.Tr>
          </Table.Thead>
          <Table.Tbody>
            {items.map((row) => (
              <Table.Tr key={row.id}>
                <Table.Td>
                  <Text ff="monospace" size="sm">
                    {row.code}
                  </Text>
                </Table.Td>
                <Table.Td>{row.name}</Table.Td>
                <Table.Td>
                  <Text size="sm" c="dimmed" lineClamp={2}>
                    {row.description || "—"}
                  </Text>
                </Table.Td>
                <Table.Td>
                  <Text size="sm" c="dimmed">
                    {row.updated_at}
                  </Text>
                </Table.Td>
                <Table.Td>
                  <Group gap="xs" justify="flex-end">
                    <CanAccess
                      resource={ModuleId.businessDomains}
                      action={ModuleAction.edit}
                    >
                      <Button
                        size="xs"
                        variant="light"
                        onClick={() => {
                          setEditTarget(row);
                          editForm.setValues({
                            name: row.name,
                            description: row.description ?? "",
                          });
                        }}
                      >
                        {t("actions.edit")}
                      </Button>
                    </CanAccess>
                    <CanAccess
                      resource={ModuleId.businessDomains}
                      action={ModuleAction.delete}
                    >
                      <Button
                        size="xs"
                        color="red"
                        variant="light"
                        onClick={() => setDeleteTarget(row)}
                      >
                        {t("actions.delete")}
                      </Button>
                    </CanAccess>
                  </Group>
                </Table.Td>
              </Table.Tr>
            ))}
          </Table.Tbody>
        </Table>
      )}

      <Modal
        opened={createOpen}
        onClose={() => setCreateOpen(false)}
        title={t("businessDomains.create.title")}
      >
        <form onSubmit={createForm.onSubmit((v) => void submitCreate(v))}>
          <Stack>
            <TextInput
              label={t("businessDomains.fields.code")}
              required
              {...createForm.getInputProps("code")}
            />
            <TextInput
              label={t("businessDomains.fields.name")}
              required
              {...createForm.getInputProps("name")}
            />
            <Textarea
              label={t("businessDomains.fields.description")}
              {...createForm.getInputProps("description")}
              minRows={2}
            />
            <Button type="submit" loading={busy}>
              {t("businessDomains.create.submit")}
            </Button>
          </Stack>
        </form>
      </Modal>

      <Modal
        opened={editTarget != null}
        onClose={() => setEditTarget(null)}
        title={t("businessDomains.edit.title")}
      >
        <form onSubmit={editForm.onSubmit((v) => void submitEdit(v))}>
          <Stack>
            <TextInput
              label={t("businessDomains.fields.code")}
              value={editTarget?.code ?? ""}
              disabled
            />
            <TextInput
              label={t("businessDomains.fields.name")}
              required
              {...editForm.getInputProps("name")}
            />
            <Textarea
              label={t("businessDomains.fields.description")}
              {...editForm.getInputProps("description")}
              minRows={2}
            />
            <Button type="submit" loading={busy}>
              {t("businessDomains.edit.submit")}
            </Button>
          </Stack>
        </form>
      </Modal>

      <Modal
        opened={deleteTarget != null}
        onClose={() => setDeleteTarget(null)}
        title={t("businessDomains.delete.confirmTitle")}
      >
        <Stack>
          <Text size="sm">
            {t("businessDomains.delete.confirmBody", {
              name: deleteTarget?.name ?? "",
            })}
          </Text>
          <Group justify="flex-end">
            <Button variant="default" onClick={() => setDeleteTarget(null)}>
              {t("actions.cancel")}
            </Button>
            <Button color="red" loading={busy} onClick={() => void confirmDelete()}>
              {t("actions.delete")}
            </Button>
          </Group>
        </Stack>
      </Modal>
    </PageChrome>
  );
}
