"use client";

import {
  Button,
  Group,
  Stack,
  Text,
  Title,
} from "@mantine/core";
import { useNotification, useTranslate } from "@refinedev/core";
import { useState } from "react";

import { FormDialog } from "@/components/form/FormDialog";
import { PasswordInput } from "@/components/form/PasswordInput";
import {
  FormErrorSummary,
  saveFailureFrom,
  type SaveFailure,
} from "@/components/form/FormErrorSummary";
import { useConsoleForm } from "@/components/form/useConsoleForm";
import { changeAccountPassword } from "@/features/account/api";

type PasswordForm = {
  current_password: string;
  new_password: string;
  confirm_password: string;
};

export function PasswordSection() {
  const t = useTranslate();
  const { open } = useNotification();
  const [passwordOpen, setPasswordOpen] = useState(false);
  const [saveFailure, setSaveFailure] = useState<SaveFailure | null>(null);

  const passwordForm = useConsoleForm<PasswordForm>({
    initialValues: {
      current_password: "",
      new_password: "",
      confirm_password: "",
    },
    onValuesChange: () => setSaveFailure(null),
    validate: {
      current_password: (value) =>
        value.length > 0 ? null : t("account.validation.required"),
      new_password: (value) =>
        value.length >= 6 ? null : t("account.validation.password"),
      confirm_password: (value, values) =>
        value === values.new_password
          ? null
          : t("account.validation.passwordMatch"),
    },
  });

  function closePasswordModal() {
    setPasswordOpen(false);
    setSaveFailure(null);
    passwordForm.reset();
  }

  async function onChangePassword(values: PasswordForm) {
    try {
      await changeAccountPassword({
        current_password: values.current_password,
        new_password: values.new_password,
      });
      passwordForm.markSaved();
      setSaveFailure(null);
      passwordForm.reset();
      setPasswordOpen(false);
      open?.({
        type: "success",
        message: t("account.title"),
        description: t("account.password.success"),
      });
    } catch (err) {
      setSaveFailure(
        saveFailureFrom(
          t,
          err,
          passwordForm.applyApiError(err),
          t("account.password.error"),
        ),
      );
    }
  }

  return (
    <>
      <Group justify="space-between" align="center">
        <Title order={4}>{t("account.section.password")}</Title>
        <Button onClick={() => setPasswordOpen(true)}>
          {t("account.section.password")}
        </Button>
      </Group>
      <FormDialog
        opened={passwordOpen}
        onClose={closePasswordModal}
        title={t("account.section.password")}
        dirty={passwordForm.dirty}
        submitting={passwordForm.submitting}
        submitLabel={t("account.password.save")}
        summary={<FormErrorSummary failure={saveFailure} />}
        onSubmit={() => void passwordForm.submit(onChangePassword)}
      >
        <Stack gap="md">
          <PasswordInput
            label={t("account.fields.currentPassword")}
            withAsterisk
            {...passwordForm.fieldProps("current_password")}
          />
          <PasswordInput
            label={t("account.fields.newPassword")}
            withAsterisk
            {...passwordForm.fieldProps("new_password")}
          />
          <PasswordInput
            label={t("account.fields.confirmPassword")}
            withAsterisk
            {...passwordForm.fieldProps("confirm_password")}
          />
          <Text size="sm" c="dimmed">
            {t("account.password.hint")}
          </Text>
        </Stack>
      </FormDialog>
    </>
  );
}
