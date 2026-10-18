"use client";

import { Button, PasswordInput, Stack } from "@mantine/core";
import { useState } from "react";

import { RecordPicker } from "@/components/form/RecordPicker";
import { roleRecordAdapter } from "@/components/form/recordPickerAdapters";
import { TextField } from "@/components/form/TextField";
import {
  FormErrorSummary,
  saveFailureFrom,
  type SaveFailure,
} from "@/components/form/FormErrorSummary";
import { useConsoleForm } from "@/components/form/useConsoleForm";
import { useForm as useRefineForm, useTranslate } from "@refinedev/core";
import { HeaderAction, HeaderActions } from "@/components/layout/HeaderActions";
import { PageChrome } from "@/components/layout/PageChrome";
import { ConsoleLink } from "@/components/navigation/ConsoleLink";
import { suppressLeaveGuard } from "@/components/navigation/leaveGuard";
import { ModuleAction, ModuleId } from "@/features/console/module-identity";
import type { UserCreateValues } from "@/features/users/types";

const USER_CREATE_FORM_ID = "user-create-form";

export function UserCreateForm() {
  const t = useTranslate();
  const [saveFailure, setSaveFailure] = useState<SaveFailure | null>(null);
  const { onFinish } = useRefineForm<UserCreateValues>({
    resource: ModuleId.users,
    action: ModuleAction.create,
    redirect: "list",
    successNotification: {
      message: t("users.title"),
      description: t("users.create.success"),
      type: "success",
    },
    errorNotification: false,
  });

  const form = useConsoleForm<UserCreateValues>({
    initialValues: {
      account: "",
      display_name: "",
      password: "",
      role_id: null,
    },
    onValuesChange: () => setSaveFailure(null),
    validate: {
      account: (value) =>
        value.trim().length > 0 ? null : t("users.validation.required"),
      display_name: (value) =>
        value.trim().length > 0 ? null : t("users.validation.required"),
      password: (value) =>
        value.length >= 6 ? null : t("users.validation.password"),
    },
  });

  return (
    <PageChrome
      title={t("users.create.title")}
      status="ready"
      actions={
          <HeaderActions
            standard={
              <>
                <Button
                  component={ConsoleLink}
                  href="/console/users"
                  variant="default"
                  size="sm"
                >
                  {t("common.cancel")}
                </Button>
                <HeaderAction primary>
                  <Button type="submit" form={USER_CREATE_FORM_ID} size="sm" loading={form.submitting}>
                    {t("users.create.submit")}
                  </Button>
                </HeaderAction>
              </>
            }
          />
      }
    >
      <form
          id={USER_CREATE_FORM_ID}
          onSubmit={form.onSubmit(async (values) => {
            try {
              await onFinish({
                ...values,
                role_id: values.role_id || null,
              });
              suppressLeaveGuard();
            } catch (error) {
              setSaveFailure(
                saveFailureFrom(
                  t,
                  error,
                  form.applyApiError(error),
                  t("common.error.loadFailed"),
                ),
              );
            }
          })}
        >
          <Stack gap="sm">
            <FormErrorSummary failure={saveFailure} />
            <TextField
              label={t("users.fields.account")}
              required
              editable
              maxLength={64}
              {...form.fieldProps("account")}
            />
            <TextField
              label={t("users.fields.displayName")}
              required
              editable
              maxLength={64}
              {...form.fieldProps("display_name")}
            />
            <PasswordInput
              label={t("users.fields.password")}
              required
              maxLength={256}
              {...form.fieldProps("password")}
            />
            <RecordPicker
              editable
              label={t("users.fields.role")}
              clearable
              placeholder={t("users.roles.none")}
              adapter={roleRecordAdapter()}
              {...form.fieldProps("role_id")}
            />
          </Stack>
        </form>
    </PageChrome>
  );
}
