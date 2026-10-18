"use client";

import {
  Button,
  Divider,
  Group,
  Stack,
  Title,
} from "@mantine/core";
import {
  CanAccess,
  useGetIdentity,
  useNotification,
  useTranslate,
} from "@refinedev/core";
import { useChangeLanguage } from "next-i18next/client";
import { useEffect, useMemo, useState } from "react";

import { DisplayField } from "@/components/display/DisplayField";
import { PageError } from "@/components/feedback/PageError";
import { PageBodySkeleton } from "@/components/feedback/PageBodySkeleton";
import { FormSection } from "@/components/form/FormSection";
import { SelectField } from "@/components/form/SelectField";
import { TextField } from "@/components/form/TextField";
import {
  FormErrorSummary,
  saveFailureFrom,
  type SaveFailure,
} from "@/components/form/FormErrorSummary";
import { useConsoleForm } from "@/components/form/useConsoleForm";
import { HeaderAction, HeaderActions } from "@/components/layout/HeaderActions";
import { PageChrome } from "@/components/layout/PageChrome";
import { AccountSectionNav } from "@/features/account/AccountSectionNav";
import { ACCOUNT_SECTION } from "@/features/account/account-sections";
import { patchAccountProfile } from "@/features/account/api";

const PROFILE_FORM_ID = "account-profile-form";
import { PasswordSection } from "@/features/account/PasswordSection";
import { ModuleAction, ModuleId } from "@/features/console/module-identity";
import { McpSection } from "@/features/account/McpSection";
import { TokenList } from "@/features/tokens/TokenList";
import { FOLLOW_BROWSER_TIMEZONE } from "@/providers/display-timezone-catalog";
import { useTimeZones } from "@/providers/time-zones";
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
  const [saveFailure, setSaveFailure] = useState<SaveFailure | null>(null);

  const {
    items: timeZones,
    loading: timeZonesLoading,
    error: timeZonesError,
  } = useTimeZones();
  const catalogZones = useMemo(
    () => timeZones.map((zone) => zone.id),
    [timeZones],
  );
  const catalogZoneSet = useMemo(() => new Set(catalogZones), [catalogZones]);

  const profileForm = useConsoleForm<ProfileForm>({
    initialValues: {
      display_name: "",
      email: "",
      locale: "en-US",
      display_timezone: FOLLOW_BROWSER_TIMEZONE,
    },
    onValuesChange: () => setSaveFailure(null),
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
    profileForm.markSaved();
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
      profileForm.markSaved();
      setSaveFailure(null);
      open?.({
        type: "success",
        message: t("account.title"),
        description: t("account.profile.success"),
      });
    } catch (err) {
      setSaveFailure(
        saveFailureFrom(
          t,
          err,
          profileForm.applyApiError(err),
          t("account.profile.error"),
        ),
      );
    }
  }

  const isLocal = identity?.identity_source === "local";

  return (
    <PageChrome
      title={t("account.title")}
      description={t("account.description")}
      actions={
        <HeaderActions
          standard={
            <HeaderAction primary>
              <Button type="submit" form={PROFILE_FORM_ID} size="sm" loading={profileForm.submitting}>
                {t("account.profile.save")}
              </Button>
            </HeaderAction>
          }
        />
      }
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

            <form id={PROFILE_FORM_ID} onSubmit={profileForm.onSubmit(onSaveProfile)}>
              <Stack gap="sm">
                <FormErrorSummary failure={saveFailure} />
                <FormSection
                  title={t("account.section.profile")}
                  columns={1}
                  order={3}
                >
                <TextField
                  label={t("account.fields.displayName")}
                  withAsterisk
                  editable
                  {...profileForm.fieldProps("display_name")}
                />
                <TextField
                  label={t("account.fields.email")}
                  helper={t("account.fields.email.hint")}
                  editable
                  {...profileForm.fieldProps("email")}
                />
                <SelectField
                  label={t("account.fields.locale")}
                  data={LOCALE_SELECT_DATA}
                  allowDeselect={false}
                  editable
                  {...profileForm.fieldProps("locale")}
                />
                {timeZonesLoading ? (
                  <PageBodySkeleton rows={1} />
                ) : (
                  <>
                    {timeZonesError ? (
                      <PageError message={timeZonesError} />
                    ) : null}
                    <SelectField
                      label={t("account.fields.displayTimezone")}
                      helper={t("account.fields.displayTimezone.hint")}
                      data={timezoneSelectData}
                      searchable
                      allowDeselect={false}
                      editable
                      {...profileForm.fieldProps("display_timezone")}
                    />
                  </>
                )}
                </FormSection>
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
