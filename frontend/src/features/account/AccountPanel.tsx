"use client";

import {
  Button,
  Divider,
  Group,
  Select,
  Stack,
  TextInput,
  Title,
} from "@mantine/core";
import { useForm } from "@mantine/form";
import {
  CanAccess,
  useGetIdentity,
  useNotification,
  useTranslate,
} from "@refinedev/core";
import { useChangeLanguage } from "next-i18next/client";
import { useEffect, useState } from "react";

import { DisplayField } from "@/components/display/DisplayField";
import { PageChrome } from "@/components/layout/PageChrome";
import { patchAccountProfile } from "@/features/account/api";
import { PasswordSection } from "@/features/account/PasswordSection";
import { ModuleAction, ModuleId } from "@/features/console/module-identity";
import { TokenList } from "@/features/tokens/TokenList";
import { ApiError } from "@/lib/api";
import {
  isLocale,
  LOCALE_COOKIE_NAME,
  LOCALE_SELECT_DATA,
  type Locale,
} from "@/providers/locale-catalog";
import {
  useSessionStore,
  type CurrentUser,
} from "@/providers/session-store";

type ProfileForm = {
  display_name: string;
  email: string;
  locale: Locale;
};

export function AccountPanel() {
  const t = useTranslate();
  const { open } = useNotification();
  const { data: identity } = useGetIdentity<CurrentUser>();
  const setUser = useSessionStore((s) => s.setUser);
  const changeLanguage = useChangeLanguage(LOCALE_COOKIE_NAME);
  const [savingProfile, setSavingProfile] = useState(false);

  const profileForm = useForm<ProfileForm>({
    initialValues: {
      display_name: "",
      email: "",
      locale: "en-US",
    },
    validate: {
      display_name: (value) =>
        value.trim().length > 0 ? null : t("account.validation.required"),
    },
  });

  useEffect(() => {
    if (!identity) return;
    profileForm.setValues({
      display_name: identity.display_name,
      email: identity.email ?? "",
      locale: isLocale(identity.locale) ? identity.locale : "en-US",
    });
    // Only sync when identity id / fields change from server.
    // eslint-disable-next-line react-hooks/exhaustive-deps -- form identity is stable enough
  }, [
    identity?.id,
    identity?.display_name,
    identity?.email,
    identity?.locale,
  ]);

  async function onSaveProfile(values: ProfileForm) {
    setSavingProfile(true);
    try {
      const user = await patchAccountProfile({
        display_name: values.display_name.trim(),
        email: values.email.trim() === "" ? null : values.email.trim(),
        locale: values.locale,
      });
      setUser(user);
      if (isLocale(user.locale)) {
        await changeLanguage(user.locale);
      }
      open?.({
        type: "success",
        message: t("account.title"),
        description: t("account.profile.success"),
      });
    } catch (err) {
      open?.({
        type: "error",
        message: t("account.title"),
        description:
          err instanceof ApiError ? err.detail : t("account.profile.error"),
      });
    } finally {
      setSavingProfile(false);
    }
  }

  const isLocal = identity?.identity_source === "local";

  return (
    <PageChrome
      title={t("account.title")}
      description={t("account.description")}
    >
      <Stack gap="xl">
        <Stack gap="sm">
          <Title order={4}>{t("account.section.identity")}</Title>
          <DisplayField
            label={t("account.fields.account")}
            value={identity?.account}
          />
          <DisplayField
            label={t("account.fields.role")}
            value={identity?.role_name ?? t("users.roles.none")}
          />
          <DisplayField
            label={t("account.fields.identitySource")}
            value={identity?.identity_source}
          />
        </Stack>

        <Divider />

        <form onSubmit={profileForm.onSubmit(onSaveProfile)}>
          <Stack gap="sm">
            <Title order={4}>{t("account.section.profile")}</Title>
            <TextInput
              label={t("account.fields.displayName")}
              withAsterisk
              {...profileForm.getInputProps("display_name")}
            />
            <TextInput
              label={t("account.fields.email")}
              description={t("account.fields.email.hint")}
              {...profileForm.getInputProps("email")}
            />
            <Select
              label={t("account.fields.locale")}
              data={LOCALE_SELECT_DATA}
              allowDeselect={false}
              {...profileForm.getInputProps("locale")}
            />
            <Group justify="flex-end">
              <Button type="submit" loading={savingProfile}>
                {t("account.profile.save")}
              </Button>
            </Group>
          </Stack>
        </form>

        {isLocal ? (
          <>
            <Divider />
            <PasswordSection />
          </>
        ) : null}

        <Divider />

        <CanAccess resource={ModuleId.tokens} action={ModuleAction.list}>
          <TokenList />
        </CanAccess>
      </Stack>
    </PageChrome>
  );
}
