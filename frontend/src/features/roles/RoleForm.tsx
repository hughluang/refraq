"use client";

import { Button, Stack } from "@mantine/core";
import { useCallback, useEffect, useRef, useState } from "react";

import { presentProblemNotification } from "@/components/feedback/presentProblemNotification";
import { presentSaveFailure } from "@/components/feedback/presentSaveFailure";
import { TextField } from "@/components/form/TextField";
import { useConsoleForm } from "@/components/form/useConsoleForm";
import {
  useCreate,
  useOne,
  useTranslate,
  useUpdate,
} from "@refinedev/core";

import { ConsoleLink } from "@/components/navigation/ConsoleLink";
import { suppressLeaveGuard } from "@/components/navigation/leaveGuard";
import { useConsoleNavigation } from "@/components/navigation/useConsoleNavigation";

import { HeaderAction, HeaderActions } from "@/components/layout/HeaderActions";
import { PageChrome } from "@/components/layout/PageChrome";
import { ModuleId } from "@/features/console/module-identity";
import { PermissionEditor } from "@/features/roles/PermissionEditor";
import type {
  PermissionCatalogEntry,
  RoleFormValues,
  RoleRow,
} from "@/features/roles/types";
import { apiClient } from "@/lib/api";

const ROLE_FORM_ID = "role-record-form";

type RoleFormProps = {
  mode: "create" | "edit";
  roleId?: string;
};

export function RoleForm({ mode, roleId }: RoleFormProps) {
  const t = useTranslate();
  const tRef = useRef(t);
  tRef.current = t;
  const { push } = useConsoleNavigation();
  const [catalog, setCatalog] = useState<PermissionCatalogEntry[] | null>(null);
  const [catalogFailed, setCatalogFailed] = useState(false);
  const [catalogAttempt, setCatalogAttempt] = useState(0);

  const roleQuery = useOne<RoleRow>({
    resource: ModuleId.roles,
    id: roleId ?? "",
    queryOptions: { enabled: mode === "edit" && Boolean(roleId) },
    errorNotification: false,
  });
  const refetchRoleRef = useRef(roleQuery.query.refetch);
  refetchRoleRef.current = roleQuery.query.refetch;

  const { mutate: createRole } = useCreate<RoleRow>();
  const { mutate: updateRole } = useUpdate<RoleRow>();

  const form = useConsoleForm<RoleFormValues>({
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

  const reloadCatalog = useCallback(() => {
    setCatalogAttempt((value) => value + 1);
  }, []);

  useEffect(() => {
    let cancelled = false;
    setCatalog(null);
    setCatalogFailed(false);
    void (async () => {
      try {
        const data = await apiClient<{ items: PermissionCatalogEntry[] }>(
          "/permissions",
        );
        if (!cancelled) setCatalog(data.items);
      } catch (error) {
        if (cancelled) return;
        setCatalogFailed(true);
        presentProblemNotification(tRef.current, error, { onRetry: reloadCatalog });
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [catalogAttempt, reloadCatalog]);

  useEffect(() => {
    if (mode !== "edit" || !roleQuery.query.isError) return;
    presentProblemNotification(tRef.current, roleQuery.query.error, {
      onRetry: () => {
        void refetchRoleRef.current();
      },
    });
  }, [mode, roleQuery.query.error, roleQuery.query.isError]);

  useEffect(() => {
    const role = roleQuery.result;
    if (mode === "edit" && role) {
      form.setValues({
        key: role.key,
        name: role.name,
        permissions: [...role.permissions],
      });
      form.markSaved();
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps -- sync once when role loads
  }, [mode, roleQuery.result]);

  function submit(values: RoleFormValues) {
    return new Promise<void>((resolve) => {
      if (mode === "create") {
        createRole(
          {
            resource: ModuleId.roles,
            values,
            successNotification: {
              message: t("roles.title"),
              description: t("roles.create.success"),
              type: "success",
            },
            errorNotification: false,
          },
          {
            onSuccess: () => {
              suppressLeaveGuard();
              push("/console/roles");
              resolve();
            },
            onError: (error) => {
              presentSaveFailure(t, error, form.applyApiError);
              resolve();
            },
          },
        );
        return;
      }
      if (!roleId) {
        resolve();
        return;
      }
      updateRole(
        {
          resource: ModuleId.roles,
          id: roleId,
          values: { name: values.name, permissions: values.permissions },
          successNotification: {
            message: t("roles.title"),
            description: t("roles.update.success"),
            type: "success",
          },
          errorNotification: false,
        },
        {
          onSuccess: () => {
            suppressLeaveGuard();
            push("/console/roles");
            resolve();
          },
          onError: (error) => {
            presentSaveFailure(t, error, form.applyApiError);
            resolve();
          },
        },
      );
    });
  }

  const roleFailed = mode === "edit" && Boolean(roleQuery.query.isError);
  const locked = mode === "edit" && Boolean(roleQuery.result?.locked);
  const visibleCatalog =
    catalog != null && !catalogFailed && !roleFailed ? catalog : null;
  const pageStatus = roleFailed || catalogFailed
    ? "unloaded"
    : catalog == null
      ? "loading"
      : "ready";

  function retryLoad() {
    if (catalogFailed) reloadCatalog();
    if (roleFailed) void refetchRoleRef.current();
  }

  if (mode === "edit" && roleQuery.query.isLoading) {
    return <PageChrome title={t("roles.edit.title")} status="loading" />;
  }

  return (
    <PageChrome
      title={mode === "create" ? t("roles.create.title") : t("roles.title")}
      recordTitle={mode === "edit" ? roleQuery.result?.name : undefined}
      recent={
        mode === "edit" && roleQuery.result
          ? { moduleId: "roles", title: roleQuery.result.name }
          : undefined
      }
      status={pageStatus}
      onRetry={pageStatus === "unloaded" ? retryLoad : undefined}
      actions={
        visibleCatalog ? (
          <HeaderActions
            standard={
              <>
                <Button
                  component={ConsoleLink}
                  href="/console/roles"
                  variant="default"
                  size="sm"
                >
                  {t("common.cancel")}
                </Button>
                {locked ? null : (
                  <HeaderAction primary>
                    <Button type="submit" form={ROLE_FORM_ID} size="sm" loading={form.submitting}>
                      {mode === "create"
                        ? t("roles.create.submit")
                        : t("roles.edit.submit")}
                    </Button>
                  </HeaderAction>
                )}
              </>
            }
          />
        ) : undefined
      }
    >
      {visibleCatalog ? (
        <form
          id={ROLE_FORM_ID}
          onSubmit={locked ? (event) => event.preventDefault() : form.onSubmit(submit)}
        >
          <Stack gap="sm">
            <TextField
              label={t("roles.fields.key")}
              required={mode === "create"}
              editable={mode === "create"}
              maxLength={64}
              {...form.fieldProps("key")}
            />
            <TextField
              label={t("roles.fields.name")}
              required
              editable={!locked}
              maxLength={64}
              {...form.fieldProps("name")}
            />
            <PermissionEditor
              catalog={visibleCatalog}
              selected={form.values.permissions}
              locked={locked}
              onChange={(permissions) => form.setFieldValue("permissions", permissions)}
            />
          </Stack>
        </form>
      ) : null}
    </PageChrome>
  );
}
