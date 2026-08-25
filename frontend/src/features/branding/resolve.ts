import type { Locale } from "@/providers/locale-catalog";
import type {
  PublicBranding,
  ResolvedBranding,
} from "@/features/branding/types";

function normalized(value: string | undefined): string {
  return value?.trim() ?? "";
}

export function resolveBranding(
  branding: Pick<PublicBranding, "brand_names" | "taglines">,
  locale: Locale,
  defaultProductDescription: string,
  defaultLocale: Locale,
  catalog: readonly Locale[],
): ResolvedBranding {
  const configuredNames = catalog
    .map((code) => ({
      code,
      value: normalized(branding.brand_names[code]),
    }))
    .filter(({ value }) => value.length > 0);

  if (configuredNames.length === 0) {
    return {
      brandName: "Refraq",
      tagline: defaultProductDescription,
    };
  }

  const currentName = normalized(branding.brand_names[locale]);
  const defaultName = normalized(branding.brand_names[defaultLocale]);

  return {
    brandName: currentName || defaultName || configuredNames[0].value,
    tagline: normalized(branding.taglines[locale]),
  };
}

export function browserAssetUrl(url: string | null): string | null {
  if (!url) return null;
  if (url.startsWith("/api/")) return url;
  return null;
}
