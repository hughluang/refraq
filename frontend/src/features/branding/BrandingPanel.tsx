"use client";

import { generateColors } from "@mantine/colors-generator";
import {
  Alert,
  Button,
  ColorInput,
  DEFAULT_THEME,
  FileInput,
  Group,
  Image,
  Paper,
  SimpleGrid,
  Stack,
  Switch,
  Tabs,
  Text,
  TextInput,
  Title,
} from "@mantine/core";
import { useForm } from "@mantine/form";
import { useDisclosure } from "@mantine/hooks";
import { useCan, useNotification, useTranslate } from "@refinedev/core";
import { useRouter } from "next/navigation";
import { useCallback, useEffect, useMemo, useState } from "react";

import { ConfirmActionModal } from "@/components/feedback/ConfirmActionModal";
import { PageBodySkeleton } from "@/components/feedback/PageBodySkeleton";
import { PageError } from "@/components/feedback/PageError";
import { PageChrome } from "@/components/layout/PageChrome";
import {
  deleteBrandingAsset,
  fetchPublicBranding,
  resetBranding,
  updateBranding,
  uploadBrandingAsset,
} from "@/features/branding/api";
import { useBranding } from "@/features/branding/BrandingProvider";
import {
  contrastRatio,
  isHexColor,
  warnsInsufficientCustomContrast,
} from "@/features/branding/color";
import {
  browserAssetUrl,
  resolveBranding,
} from "@/features/branding/resolve";
import {
  DEFAULT_BRANDING,
  DEFAULT_PRIMARY_COLOR,
  showsRestoreAssetControl,
  type LocalizedBrandingText,
  type PublicBranding,
} from "@/features/branding/types";
import {
  ModuleAction,
  ModuleId,
} from "@/features/console/module-identity";
import { ApiError } from "@/lib/api";
import {
  getDefaultLocale,
  LOCALE_CATALOG,
  SUPPORTED_LOCALES,
  type Locale,
} from "@/providers/locale-catalog";

type FormValues = {
  brandNames: Record<Locale, string>;
  taglines: Record<Locale, string>;
  primaryColor: string;
  showBrandNameWithLogo: boolean;
  showLogo: boolean;
};

function emptyLocalized(): Record<Locale, string> {
  return Object.fromEntries(
    LOCALE_CATALOG.map(({ code }) => [code, ""]),
  ) as Record<Locale, string>;
}

function formValues(branding: PublicBranding): FormValues {
  return {
    brandNames: {
      ...emptyLocalized(),
      ...branding.brand_names,
    },
    taglines: {
      ...emptyLocalized(),
      ...branding.taglines,
    },
    primaryColor: branding.primary_color ?? "",
    showBrandNameWithLogo: branding.show_brand_name_with_logo,
    showLogo: branding.show_logo,
  };
}

function compactLocalized(
  values: Record<Locale, string>,
): LocalizedBrandingText {
  return Object.fromEntries(
    Object.entries(values)
      .map(([locale, value]) => [locale, value.trim()])
      .filter(([, value]) => value.length > 0),
  ) as LocalizedBrandingText;
}

function useObjectUrl(file: File | null): string | null {
  const url = useMemo(() => (file ? URL.createObjectURL(file) : null), [file]);
  useEffect(
    () => () => {
      if (url) URL.revokeObjectURL(url);
    },
    [url],
  );
  return url;
}

export function BrandingPanel() {
  const t = useTranslate();
  const router = useRouter();
  const { replaceBranding } = useBranding();
  const { open: notify } = useNotification();
  const { data: canWrite } = useCan({
    resource: ModuleId.branding,
    action: ModuleAction.edit,
  });
  const [resetOpened, resetModal] = useDisclosure();
  const [branding, setBranding] = useState<PublicBranding>(DEFAULT_BRANDING);
  const [locale, setLocale] = useState<Locale>(LOCALE_CATALOG[0].code);
  const [logoFile, setLogoFile] = useState<File | null>(null);
  const [faviconFile, setFaviconFile] = useState<File | null>(null);
  const [logoCleared, setLogoCleared] = useState(false);
  const [faviconCleared, setFaviconCleared] = useState(false);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [resetting, setResetting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const form = useForm<FormValues>({
    mode: "controlled",
    initialValues: formValues(DEFAULT_BRANDING),
    validate: {
      primaryColor: (value) =>
        value.length === 0 || isHexColor(value)
          ? null
          : t("branding.validation.color"),
    },
  });
  const { resetDirty, setValues } = form;

  const applyBranding = useCallback(
    (next: PublicBranding) => {
      setBranding(next);
      setValues(formValues(next));
      resetDirty(formValues(next));
      setLogoFile(null);
      setFaviconFile(null);
      setLogoCleared(false);
      setFaviconCleared(false);
    },
    [resetDirty, setValues],
  );

  const publishBranding = useCallback(
    (next: PublicBranding) => {
      applyBranding(next);
      replaceBranding(next);
      router.refresh();
    },
    [applyBranding, replaceBranding, router],
  );

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      applyBranding(await fetchPublicBranding());
    } catch (err) {
      setError(
        err instanceof ApiError ? err.detail : t("common.error.loadFailed"),
      );
    } finally {
      setLoading(false);
    }
  }, [applyBranding, t]);

  useEffect(() => {
    void load();
  }, [load]);

  const logoDraftUrl = useObjectUrl(logoFile);
  const faviconDraftUrl = useObjectUrl(faviconFile);
  const logoUrl =
    logoDraftUrl
    ?? (logoCleared ? null : browserAssetUrl(branding.logo_url));
  const faviconUrl =
    faviconDraftUrl
    ?? (faviconCleared ? null : browserAssetUrl(branding.favicon_url));
  const previewColor =
    form.values.primaryColor && isHexColor(form.values.primaryColor)
      ? generateColors(form.values.primaryColor)[6]
      : DEFAULT_THEME.colors.blue[6];
  const contrast = contrastRatio(previewColor);
  const contrastWarning = warnsInsufficientCustomContrast(
    form.values.primaryColor,
    contrast.ratio,
  );
  const previewBranding = resolveBranding(
    {
      brand_names: form.values.brandNames,
      taglines: form.values.taglines,
    },
    locale,
    t("app.description"),
    getDefaultLocale(),
    SUPPORTED_LOCALES,
  );

  async function save(values: FormValues) {
    setSaving(true);
    try {
      const color = values.primaryColor || null;
      let next = await updateBranding({
        brand_names: compactLocalized(values.brandNames),
        taglines: compactLocalized(values.taglines),
        primary_color: color,
        primary_shades: color ? [...generateColors(color)] : null,
        show_logo: values.showLogo,
        show_brand_name_with_logo: values.showBrandNameWithLogo,
      });
      const assetsChanged = Boolean(
        logoFile
        || faviconFile
        || (logoCleared && branding.logo_url)
        || (faviconCleared && branding.favicon_url),
      );
      if (logoFile) {
        await uploadBrandingAsset("logo", logoFile);
      } else if (logoCleared && branding.logo_url) {
        await deleteBrandingAsset("logo");
      }
      if (faviconFile) {
        await uploadBrandingAsset("favicon", faviconFile);
      } else if (faviconCleared && branding.favicon_url) {
        await deleteBrandingAsset("favicon");
      }
      if (assetsChanged) {
        next = await fetchPublicBranding();
      }
      publishBranding(next);
      notify?.({
        type: "success",
        message: t("branding.title"),
        description: t("branding.save.success"),
      });
    } catch (err) {
      notify?.({
        type: "error",
        message: t("branding.title"),
        description: err instanceof ApiError ? err.detail : t("common.error"),
      });
      await load();
    } finally {
      setSaving(false);
    }
  }

  async function resetAll() {
    setResetting(true);
    try {
      publishBranding(await resetBranding());
      resetModal.close();
      notify?.({
        type: "success",
        message: t("branding.title"),
        description: t("branding.reset.success"),
      });
    } catch (err) {
      notify?.({
        type: "error",
        message: t("branding.title"),
        description: err instanceof ApiError ? err.detail : t("common.error"),
      });
    } finally {
      setResetting(false);
    }
  }

  return (
    <PageChrome
      title={t("branding.title")}
      description={t("branding.description")}
      actions={
        canWrite?.can ? (
          <Group>
            <Button variant="default" onClick={resetModal.open}>
              {t("branding.reset")}
            </Button>
            <Button
              loading={saving}
              onClick={() => form.onSubmit(save)()}
            >
              {t("branding.save")}
            </Button>
          </Group>
        ) : undefined
      }
    >
      {loading ? <PageBodySkeleton rows={8} /> : null}
      {!loading && error ? (
        <PageError message={error} onRetry={() => void load()} />
      ) : null}
      {!loading && !error ? (
        <SimpleGrid cols={{ base: 1, lg: 2 }} spacing="xl">
          <Stack gap="lg">
            <Paper withBorder p="md">
              <Tabs
                value={locale}
                onChange={(value) => {
                  if (value) setLocale(value as Locale);
                }}
              >
                <Tabs.List>
                  {LOCALE_CATALOG.map(({ code }) => (
                    <Tabs.Tab key={code} value={code}>
                      {t(`locale.label.${code}`)}
                    </Tabs.Tab>
                  ))}
                </Tabs.List>
                {LOCALE_CATALOG.map(({ code }) => (
                  <Tabs.Panel key={code} value={code} pt="md">
                    <Stack>
                      <TextInput
                        label={t("branding.fields.name")}
                        maxLength={80}
                        disabled={!canWrite?.can}
                        {...form.getInputProps(`brandNames.${code}`)}
                        rightSection={
                          canWrite?.can && form.values.brandNames[code] ? (
                            <Button
                              size="compact-xs"
                              variant="subtle"
                              onClick={() =>
                                form.setFieldValue(`brandNames.${code}`, "")
                              }
                            >
                              {t("branding.clear")}
                            </Button>
                          ) : undefined
                        }
                        rightSectionWidth={64}
                      />
                      <TextInput
                        label={t("branding.fields.tagline")}
                        description={t("branding.fields.tagline.help")}
                        maxLength={160}
                        disabled={!canWrite?.can}
                        {...form.getInputProps(`taglines.${code}`)}
                        rightSection={
                          canWrite?.can && form.values.taglines[code] ? (
                            <Button
                              size="compact-xs"
                              variant="subtle"
                              onClick={() =>
                                form.setFieldValue(`taglines.${code}`, "")
                              }
                            >
                              {t("branding.clear")}
                            </Button>
                          ) : undefined
                        }
                        rightSectionWidth={64}
                      />
                    </Stack>
                  </Tabs.Panel>
                ))}
              </Tabs>
            </Paper>

            <Paper withBorder p="md">
              <Stack>
                <ColorInput
                  label={t("branding.fields.color")}
                  placeholder={DEFAULT_PRIMARY_COLOR}
                  disabled={!canWrite?.can}
                  format="hex"
                  swatches={[
                    "#228be6",
                    "#15aabf",
                    "#12b886",
                    "#fab005",
                    "#fa5252",
                    "#7950f2",
                  ]}
                  {...form.getInputProps("primaryColor")}
                />
                <Group justify="space-between">
                  <Text size="xs" c="dimmed">
                    {t("branding.contrast.ratio", {
                      ratio: contrast.ratio.toFixed(2),
                    })}
                  </Text>
                  {canWrite?.can && form.values.primaryColor ? (
                    <Button
                      size="compact-xs"
                      variant="subtle"
                      onClick={() => form.setFieldValue("primaryColor", "")}
                    >
                      {t("branding.clear")}
                    </Button>
                  ) : null}
                </Group>
                {contrastWarning ? (
                  <Alert color="yellow" title={t("branding.contrast.title")}>
                    {t("branding.contrast.body")}
                  </Alert>
                ) : null}
                <Switch
                  label={t("branding.fields.showLogo")}
                  disabled={!canWrite?.can}
                  {...form.getInputProps("showLogo", {
                    type: "checkbox",
                  })}
                />
                <Switch
                  label={t("branding.fields.showName")}
                  disabled={!canWrite?.can}
                  {...form.getInputProps("showBrandNameWithLogo", {
                    type: "checkbox",
                  })}
                />
              </Stack>
            </Paper>

            <Paper withBorder p="md">
              <Stack>
                <FileInput
                  label={t("branding.fields.logo")}
                  description={t("branding.fields.logo.help")}
                  accept="image/png,image/jpeg,image/svg+xml"
                  clearable
                  value={logoFile}
                  disabled={!canWrite?.can}
                  onChange={(file) => {
                    setLogoFile(file);
                    if (file) setLogoCleared(false);
                  }}
                />
                {canWrite?.can
                && showsRestoreAssetControl(
                  branding.logo_source,
                  Boolean(logoFile),
                  logoCleared,
                ) ? (
                  <Button
                    variant="light"
                    color="red"
                    onClick={() => {
                      setLogoFile(null);
                      setLogoCleared(true);
                    }}
                  >
                    {t("branding.assets.clearLogo")}
                  </Button>
                ) : null}
                <FileInput
                  label={t("branding.fields.favicon")}
                  description={t("branding.fields.favicon.help")}
                  accept="image/png,image/vnd.microsoft.icon,.ico"
                  clearable
                  value={faviconFile}
                  disabled={!canWrite?.can}
                  onChange={(file) => {
                    setFaviconFile(file);
                    if (file) setFaviconCleared(false);
                  }}
                />
                {canWrite?.can
                && showsRestoreAssetControl(
                  branding.favicon_source,
                  Boolean(faviconFile),
                  faviconCleared,
                ) ? (
                  <Button
                    variant="light"
                    color="red"
                    onClick={() => {
                      setFaviconFile(null);
                      setFaviconCleared(true);
                    }}
                  >
                    {t("branding.assets.clearFavicon")}
                  </Button>
                ) : null}
              </Stack>
            </Paper>
          </Stack>

          <Stack>
            <Text fw={600}>{t("branding.preview.title")}</Text>
            <Paper withBorder p="xl">
              <Stack>
                <Group>
                  {logoUrl && form.values.showLogo ? (
                    <Image
                      src={logoUrl}
                      alt={previewBranding.brandName}
                      h={48}
                      w="auto"
                      maw={180}
                      fit="contain"
                    />
                  ) : null}
                  {form.values.showBrandNameWithLogo ? (
                    <Title order={3}>{previewBranding.brandName}</Title>
                  ) : null}
                </Group>
                {previewBranding.tagline ? (
                  <Text c="dimmed">{previewBranding.tagline}</Text>
                ) : null}
                <Button
                  style={{
                    backgroundColor: previewColor,
                    color: contrast.foreground,
                  }}
                >
                  {t("branding.preview.action")}
                </Button>
                <Group gap="xs">
                  <Text size="xs" c="dimmed">
                    {t("branding.preview.favicon")}
                  </Text>
                  {faviconUrl ? (
                    <Image
                      src={faviconUrl}
                      alt=""
                      h={24}
                      w={24}
                      fit="contain"
                    />
                  ) : null}
                </Group>
                <Text size="xs" c="dimmed">
                  {t("branding.preview.only")}
                </Text>
              </Stack>
            </Paper>
          </Stack>
        </SimpleGrid>
      ) : null}

      <ConfirmActionModal
        opened={resetOpened}
        onClose={resetModal.close}
        title={t("branding.reset.confirmTitle")}
        body={t("branding.reset.confirmBody")}
        confirmLabel={t("branding.reset")}
        confirmColor="red"
        loading={resetting}
        onConfirm={() => void resetAll()}
      />
    </PageChrome>
  );
}
