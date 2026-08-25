import type { Locale } from "@/providers/locale-catalog";

export type LocalizedBrandingText = Partial<Record<Locale, string>>;

export type BrandingAssetSource = "seed" | "user";

export type PublicBranding = {
  brand_names: LocalizedBrandingText;
  taglines: LocalizedBrandingText;
  primary_color: string | null;
  primary_shades: string[] | null;
  show_logo: boolean;
  show_brand_name_with_logo: boolean;
  logo_url: string | null;
  favicon_url: string | null;
  logo_source: BrandingAssetSource | null;
  favicon_source: BrandingAssetSource | null;
};

export type ResolvedBranding = {
  brandName: string;
  tagline: string;
};

export type BrandingUpdate = {
  brand_names: LocalizedBrandingText | null;
  taglines: LocalizedBrandingText | null;
  primary_color: string | null;
  primary_shades: string[] | null;
  show_logo: boolean;
  show_brand_name_with_logo: boolean;
};

export const DEFAULT_BRANDING: PublicBranding = {
  brand_names: {},
  taglines: {},
  primary_color: null,
  primary_shades: null,
  show_logo: true,
  show_brand_name_with_logo: true,
  logo_url: null,
  favicon_url: null,
  logo_source: null,
  favicon_source: null,
};

export const DEFAULT_PRIMARY_COLOR = "#228be6";

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null;
}

function localizedText(value: unknown): PublicBranding["brand_names"] {
  if (!isRecord(value)) return {};
  return Object.fromEntries(
    Object.entries(value).filter(
      ([, text]) => typeof text === "string" && text.trim().length > 0,
    ),
  );
}

export function parseAssetSource(
  value: unknown,
): BrandingAssetSource | null {
  return value === "seed" || value === "user" ? value : null;
}

export function parsePublicBranding(value: unknown): PublicBranding {
  if (!isRecord(value)) return DEFAULT_BRANDING;
  const shades = Array.isArray(value.primary_shades)
    && value.primary_shades.length === 10
    && value.primary_shades.every((shade) => typeof shade === "string")
    ? value.primary_shades
    : null;

  return {
    brand_names: localizedText(value.brand_names),
    taglines: localizedText(value.taglines),
    primary_color:
      typeof value.primary_color === "string" ? value.primary_color : null,
    primary_shades: shades,
    show_logo:
      typeof value.show_logo === "boolean" ? value.show_logo : true,
    show_brand_name_with_logo:
      typeof value.show_brand_name_with_logo === "boolean"
        ? value.show_brand_name_with_logo
        : true,
    logo_url: typeof value.logo_url === "string" ? value.logo_url : null,
    favicon_url:
      typeof value.favicon_url === "string" ? value.favicon_url : null,
    logo_source: parseAssetSource(value.logo_source),
    favicon_source: parseAssetSource(value.favicon_source),
  };
}

export function showsRestoreAssetControl(
  source: BrandingAssetSource | null,
  hasDraftFile: boolean,
  cleared: boolean,
): boolean {
  return !cleared && (hasDraftFile || source === "user");
}
