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
import { useEffect, useMemo, useState } from "react";

import { DisplayField } from "@/components/display/DisplayField";
import { PageChrome } from "@/components/layout/PageChrome";
import { AccountSectionNav } from "@/features/account/AccountSectionNav";
import { ACCOUNT_SECTION } from "@/features/account/account-sections";
import { patchAccountProfile } from "@/features/account/api";
import { PasswordSection } from "@/features/account/PasswordSection";
import { ModuleAction, ModuleId } from "@/features/console/module-identity";
import { McpSection } from "@/features/account/McpSection";
import { TokenList } from "@/features/tokens/TokenList";
import { ApiError } from "@/lib/api";
import {
  FOLLOW_BROWSER_TIMEZONE,
  listIanaTimeZones,
} from "@/providers/display-timezone-catalog";
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
  display_timezone: string;
};

export function AccountPanel() {
  const t = useTranslate();
  const { open } = useNotification();
  const { data: identity } = useGetIdentity<CurrentUser>();
  const setUser = useSessionStore((s) => s.setUser);
  const changeLanguage = useChangeLanguage(LOCALE_COOKIE_NAME);
  const [savingProfile, setSavingProfile] = useState(false);

  const catalogZones = useMemo(() => listIanaTimeZones(), []);
  const catalogZoneSet = useMemo(() => new Set(catalogZones), [catalogZones]);

  const profileForm = useForm<ProfileForm>({
    initialValues: {
      display_name: "",
      email: "",
      locale: "en-US",
      display_timezone: FOLLOW_BROWSER_TIMEZONE,
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
      // null → follow browser; non-null (even outside ICU catalog) keep as-is.
      display_timezone: identity.display_timezone ?? FOLLOW_BROWSER_TIMEZONE,
    });
    // Only sync when identity id / fields change from server.
    // eslint-disable-next-line react-hooks/exhaustive-deps -- form identity is stable enough
  }, [
    identity?.id,
    identity?.display_name,
    identity?.email,
    identity?.locale,
    identity?.display_timezone,
  ]);

  const timezoneSelectData = useMemo(() => {
    const stored = identity?.display_timezone;
    const extra =
      stored && !catalogZoneSet.has(stored)
        ? [{ value: stored, label: stored }]
        : [];
    return [
      {
        value: FOLLOW_BROWSER_TIMEZONE,
        label: t("account.fields.displayTimezone.browser"),
      },
      ...extra,
      ...catalogZones.map((zone) => ({ value: zone, label: zone })),
    ];
  }, [t, catalogZones, catalogZoneSet, identity?.display_timezone]);

  async function onSaveProfile(values: ProfileForm) {
    setSavingProfile(true);
    try {
      const user = await patchAccountProfile({
        display_name: values.display_name.trim(),
        email: values.email.trim() === "" ? null : values.email.trim(),
        locale: values.locale,
        display_timezone:
          values.display_timezone === FOLLOW_BROWSER_TIMEZONE
            ? null
            : values.display_timezone,
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
      <Group align="flex-start" wrap="nowrap" gap="xl">
        <Stack gap="xl" style={{ flex: 1, minWidth: 0 }}>
          <Stack id={ACCOUNT_SECTION.profile} gap="xl">
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
                value={
                  identity?.identity_source
                    ? t(`identitySource.${identity.identity_source}`)
                    : undefined
                }
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
                <Select
                  label={t("account.fields.displayTimezone")}
                  description={t("account.fields.displayTimezone.hint")}
                  data={timezoneSelectData}
                  searchable
                  allowDeselect={false}
                  {...profileForm.getInputProps("display_timezone")}
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
          </Stack>

          <Divider />

          <CanAccess resource={ModuleId.tokens} action={ModuleAction.list}>
            <div id={ACCOUNT_SECTION.tokens}>
              <TokenList />
            </div>
          </CanAccess>

          <Divider />

          <div id={ACCOUNT_SECTION.mcp}>
            <McpSection />
          </div>
        </Stack>
        <AccountSectionNav />
      </Group>
    </PageChrome>
  );
}
