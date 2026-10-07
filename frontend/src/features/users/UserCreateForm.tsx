"use client";

import {
  Button,
  Group,
  PasswordInput,
  Stack,
} from "@mantine/core";
import { useForm } from "@mantine/form";

import { SelectField } from "@/components/form/SelectField";
import { TextField } from "@/components/form/TextField";
import {
  useForm as useRefineForm,
  useList,
  useTranslate,
} from "@refinedev/core";
import Link from "next/link";

import { PageBodySkeleton } from "@/components/feedback/PageBodySkeleton";
import { PageChrome } from "@/components/layout/PageChrome";
import { ModuleAction, ModuleId } from "@/features/console/module-identity";
import type { RoleRow } from "@/features/roles/types";
import type { UserCreateValues } from "@/features/users/types";
import { problemMessage } from "@/lib/problem";

export function UserCreateForm() {
  const t = useTranslate();
  const rolesQuery = useList<RoleRow>({
    resource: ModuleId.roles,
    pagination: { mode: "off" },
  });
  const { onFinish, formLoading } = useRefineForm<UserCreateValues>({
    resource: ModuleId.users,
    action: ModuleAction.create,
    redirect: "list",
    successNotification: {
      message: t("users.title"),
      description: t("users.create.success"),
      type: "success",
    },
    errorNotification: (error) => ({
      message: t("users.title"),
      description:
        problemMessage(t, error, t("common.error.loadFailed")),
      type: "error",
    }),
  });

  const form = useForm<UserCreateValues>({
    initialValues: {
      account: "",
      display_name: "",
      password: "",
      role_id: null,
    },
    validate: {
      account: (value) =>
        value.trim().length > 0 ? null : t("users.validation.required"),
      display_name: (value) =>
        value.trim().length > 0 ? null : t("users.validation.required"),
      password: (value) =>
        value.length >= 6 ? null : t("users.validation.password"),
    },
  });

  const roleOptions = (rolesQuery.result?.data ?? []).map((role) => ({
    value: role.id,
    label: role.name,
  }));

  return (
    <PageChrome title={t("users.create.title")}>
      {rolesQuery.query.isLoading ? (
        <PageBodySkeleton rows={5} />
      ) : (
        <form
          onSubmit={form.onSubmit((values) =>
            void onFinish({
              ...values,
              role_id: values.role_id || null,
            }),
          )}
        >
          <Stack gap="sm">
            <TextField
              label={t("users.fields.account")}
              required
              editable
              maxLength={64}
              {...form.getInputProps("account")}
            />
            <TextField
              label={t("users.fields.displayName")}
              required
              editable
              maxLength={64}
              {...form.getInputProps("display_name")}
            />
            <PasswordInput
              label={t("users.fields.password")}
              required
              maxLength={256}
              {...form.getInputProps("password")}
            />
            <SelectField
              editable
              label={t("users.fields.role")}
              clearable
              placeholder={t("users.roles.none")}
              data={roleOptions}
              value={form.values.role_id}
              onChange={(value) => form.setFieldValue("role_id", value)}
            />
            <Group justify="flex-end">
              <Button component={Link} href="/console/users" variant="default">
                {t("common.cancel")}
              </Button>
              <Button type="submit" loading={formLoading}>
                {t("users.create.submit")}
              </Button>
            </Group>
          </Stack>
        </form>
      )}
    </PageChrome>
  );
}
