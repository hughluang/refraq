"use client";

import {
  Button,
  Group,
  Modal,
  PasswordInput,
  Stack,
  Text,
  Title,
} from "@mantine/core";
import { useForm } from "@mantine/form";
import { useNotification, useTranslate } from "@refinedev/core";
import { useState } from "react";

import { changeAccountPassword } from "@/features/account/api";
import { ApiError } from "@/lib/api";

type PasswordForm = {
  current_password: string;
  new_password: string;
  confirm_password: string;
};

export function PasswordSection() {
  const t = useTranslate();
  const { open } = useNotification();
  const [savingPassword, setSavingPassword] = useState(false);
  const [passwordOpen, setPasswordOpen] = useState(false);

  const passwordForm = useForm<PasswordForm>({
    initialValues: {
      current_password: "",
      new_password: "",
      confirm_password: "",
    },
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
    passwordForm.reset();
  }

  async function onChangePassword(values: PasswordForm) {
    setSavingPassword(true);
    try {
      await changeAccountPassword({
        current_password: values.current_password,
        new_password: values.new_password,
      });
      passwordForm.reset();
      setPasswordOpen(false);
      open?.({
        type: "success",
        message: t("account.title"),
        description: t("account.password.success"),
      });
    } catch (err) {
      open?.({
        type: "error",
        message: t("account.title"),
        description:
          err instanceof ApiError ? err.detail : t("account.password.error"),
      });
    } finally {
      setSavingPassword(false);
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
      <Modal
        opened={passwordOpen}
        onClose={closePasswordModal}
        title={t("account.section.password")}
        centered
      >
        <form onSubmit={passwordForm.onSubmit(onChangePassword)}>
          <Stack gap="md">
            <PasswordInput
              label={t("account.fields.currentPassword")}
              withAsterisk
              {...passwordForm.getInputProps("current_password")}
            />
            <PasswordInput
              label={t("account.fields.newPassword")}
              withAsterisk
              {...passwordForm.getInputProps("new_password")}
            />
            <PasswordInput
              label={t("account.fields.confirmPassword")}
              withAsterisk
              {...passwordForm.getInputProps("confirm_password")}
            />
            <Text size="sm" c="dimmed">
              {t("account.password.hint")}
            </Text>
            <Group justify="flex-end">
              <Button
                variant="default"
                onClick={closePasswordModal}
                disabled={savingPassword}
              >
                {t("common.cancel")}
              </Button>
              <Button type="submit" loading={savingPassword}>
                {t("account.password.save")}
              </Button>
            </Group>
          </Stack>
        </form>
      </Modal>
    </>
  );
}
