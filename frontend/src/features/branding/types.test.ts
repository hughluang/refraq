import { describe, expect, it } from "vitest";

import {
  DEFAULT_BRANDING,
  parsePublicBranding,
} from "@/features/branding/types";

describe("parsePublicBranding", () => {
  it("returns product defaults for a non-object payload", () => {
    expect(parsePublicBranding(null)).toEqual(DEFAULT_BRANDING);
    expect(parsePublicBranding("nope")).toEqual(DEFAULT_BRANDING);
  });

  it("keeps a legal BrandingOut body", () => {
    const body = {
      ...DEFAULT_BRANDING,
      brand_names: { "en-US": "Acme" },
      logo_source: "seed",
      favicon_source: "user",
    };
    expect(parsePublicBranding(body)).toEqual(body);
  });

  it("drops non-string maps, short palettes, and unknown sources", () => {
    expect(
      parsePublicBranding({
        brand_names: { "en-US": "Acme", "zh-CN": 1 },
        taglines: null,
        primary_shades: ["#000000"],
        logo_source: "product",
        favicon_source: "seed",
      }),
    ).toEqual({
      ...DEFAULT_BRANDING,
      brand_names: { "en-US": "Acme" },
      favicon_source: "seed",
    });
  });

  it("defaults a missing show_logo flag to true and keeps an explicit false", () => {
    expect(parsePublicBranding({ ...DEFAULT_BRANDING }).show_logo).toBe(true);
    expect(parsePublicBranding({ show_logo: false }).show_logo).toBe(false);
  });
});
