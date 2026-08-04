"use client";

import {
  Button,
  Checkbox,
  Group,
  Stack,
  Text,
  TextInput,
} from "@mantine/core";
import { useForm } from "@mantine/form";
import {
  useCreate,
  useOne,
  useTranslate,
  useUpdate,
} from "@refinedev/core";
import Link from "next/link";
import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";

import { PageError } from "@/components/feedback/PageError";
import { PageLoader } from "@/components/feedback/PageLoader";
import { PageChrome } from "@/components/layout/PageChrome";
import type {
  PermissionCatalogEntry,
  RoleFormValues,
  RoleRow,
} from "@/features/roles/types";
import { apiClient, ApiError } from "@/lib/api";

type RoleFormProps = {
  mode: "create" | "edit";
  roleId?: string;
};

export function RoleForm({ mode, roleId }: RoleFormProps) {
  const t = useTranslate();
  const router = useRouter();
  const [catalog, setCatalog] = useState<PermissionCatalogEntry[] | null>(null);
  const [catalogError, setCatalogError] = useState<string | null>(null);

  const roleQuery = useOne<RoleRow>({
    resource: "roles",
    id: roleId ?? "",
    queryOptions: { enabled: mode === "edit" && Boolean(roleId) },
  });

  const { mutate: createRole, mutation: createMutation } = useCreate<RoleRow>();
  const { mutate: updateRole, mutation: updateMutation } = useUpdate<RoleRow>();

  const form = useForm<RoleFormValues>({
    initialValues: {
      key: "",
      name: "",
      permissions: [],
    },
    validate: {
      key: (value) =>
        mode === "create"
          ? /^[a-z][a-z0-9_]{0,63}$/.test(value)
            ? null
            : t("roles.validation.key")
          : null,
      name: (value) =>
        value.trim().length > 0 ? null : t("roles.validation.required"),
    },
  });

  useEffect(() => {
    let cancelled = false;
    void (async () => {
      try {
        const data = await apiClient<{ items: PermissionCatalogEntry[] }>(
          "/permissions",
        );
        if (!cancelled) {
          setCatalog(data.items);
        }
      } catch (error) {
        if (!cancelled) {
          setCatalogError(
            error instanceof ApiError
              ? error.detail
              : t("common.error.loadFailed"),
          );
        }
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [t]);

  useEffect(() => {
    const role = roleQuery.result;
    if (mode === "edit" && role) {
      form.setValues({
        key: role.key,
        name: role.name,
        permissions: [...role.permissions],
      });
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps -- sync once when role loads
  }, [mode, roleQuery.result]);

  const saving = createMutation.isPending || updateMutation.isPending;

  function submit(values: RoleFormValues) {
    if (mode === "create") {
      createRole(
        {
          resource: "roles",
          values,
          successNotification: {
            message: t("roles.title"),
            description: t("roles.create.success"),
            type: "success",
          },
          errorNotification: (error) => ({
            message: t("roles.title"),
            description:
              error instanceof ApiError
                ? error.detail
                : t("common.error.loadFailed"),
            type: "error",
          }),
        },
        {
          onSuccess: () => {
            router.push("/console/roles");
          },
        },
      );
      return;
    }
    if (!roleId) return;
    updateRole(
      {
        resource: "roles",
        id: roleId,
        values: { name: values.name, permissions: values.permissions },
        successNotification: {
          message: t("roles.title"),
          description: t("roles.update.success"),
          type: "success",
        },
        errorNotification: (error) => ({
          message: t("roles.title"),
          description:
            error instanceof ApiError
              ? error.detail
              : t("common.error.loadFailed"),
          type: "error",
        }),
      },
      {
        onSuccess: () => {
          router.push("/console/roles");
        },
      },
    );
  }

  if (mode === "edit" && roleQuery.query.isLoading) {
    return <PageLoader />;
  }

  if (mode === "edit" && roleQuery.result?.locked) {
    return (
      <PageChrome title={t("roles.edit.title")}>
        <PageError message={t("roles.lockedHint")} />
      </PageChrome>
    );
  }

  return (
    <PageChrome
      title={
        mode === "create" ? t("roles.create.title") : t("roles.edit.title")
      }
    >
      {catalogError ? (
        <PageError message={catalogError} />
      ) : catalog === null ? (
        <PageLoader />
      ) : (
        <form onSubmit={form.onSubmit(submit)}>
          <Stack gap="sm">
            <TextInput
              label={t("roles.fields.key")}
              required={mode === "create"}
              disabled={mode === "edit"}
              maxLength={64}
              {...form.getInputProps("key")}
            />
            <TextInput
              label={t("roles.fields.name")}
              required
              maxLength={64}
              {...form.getInputProps("name")}
            />
            <Stack gap="xs">
              <Text size="sm" fw={500}>
                {t("roles.fields.permissions")}
              </Text>
              {catalog.map((entry) => (
                <Checkbox
                  key={entry.key}
                  label={`${entry.key} — ${entry.description}`}
                  checked={form.values.permissions.includes(entry.key)}
                  onChange={(event) => {
                    const checked = event.currentTarget.checked;
                    form.setFieldValue(
                      "permissions",
                      checked
                        ? [...form.values.permissions, entry.key]
                        : form.values.permissions.filter(
                            (item) => item !== entry.key,
                          ),
                    );
                  }}
                />
              ))}
            </Stack>
            <Group justify="flex-end">
              <Button component={Link} href="/console/roles" variant="default">
                {t("common.cancel")}
              </Button>
              <Button type="submit" loading={saving}>
                {mode === "create"
                  ? t("roles.create.submit")
                  : t("roles.edit.submit")}
              </Button>
            </Group>
          </Stack>
        </form>
      )}
    </PageChrome>
  );
}
