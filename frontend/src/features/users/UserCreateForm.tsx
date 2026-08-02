"use client";

import {
  Button,
  Group,
  PasswordInput,
  Select,
  Stack,
  TextInput,
  Title,
} from "@mantine/core";
import { useForm } from "@mantine/form";
import {
  CanAccess,
  useForm as useRefineForm,
  useList,
  useTranslate,
} from "@refinedev/core";
import Link from "next/link";

import { PageError } from "@/components/feedback/PageError";
import { PageLoader } from "@/components/feedback/PageLoader";
import type { RoleRow } from "@/features/roles/types";
import type { UserCreateValues } from "@/features/users/types";
import { ApiError } from "@/lib/api";

export function UserCreateForm() {
  const t = useTranslate();
  const rolesQuery = useList<RoleRow>({
    resource: "roles",
    pagination: { mode: "off" },
  });
  const { onFinish, formLoading } = useRefineForm<UserCreateValues>({
    resource: "users",
    action: "create",
    redirect: "list",
    successNotification: {
      message: t("users.title"),
      description: t("users.create.success"),
      type: "success",
    },
    errorNotification: (error) => ({
      message: t("users.title"),
      description:
        error instanceof ApiError ? error.detail : t("common.error.loadFailed"),
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
    <CanAccess
      resource="users"
      action="create"
      fallback={<PageError message={t("forbidden.description")} />}
    >
      <Title order={3} mb="md">
        {t("users.create.title")}
      </Title>
      {rolesQuery.query.isLoading ? (
        <PageLoader />
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
            <TextInput
              label={t("users.fields.account")}
              required
              maxLength={64}
              {...form.getInputProps("account")}
            />
            <TextInput
              label={t("users.fields.displayName")}
              required
              maxLength={64}
              {...form.getInputProps("display_name")}
            />
            <PasswordInput
              label={t("users.fields.password")}
              required
              maxLength={256}
              {...form.getInputProps("password")}
            />
            <Select
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
    </CanAccess>
  );
}
