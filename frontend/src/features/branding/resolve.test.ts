import { describe, expect, it } from "vitest";

import {
  browserAssetUrl,
  resolveBranding,
} from "@/features/branding/resolve";
import { showsRestoreAssetControl } from "@/features/branding/types";
import type { Locale } from "@/providers/locale-catalog";

const CATALOG: readonly Locale[] = ["zh-CN", "en-US"];

describe("resolveBranding", () => {
  it("uses Refraq defaults when no brand name is configured", () => {
    expect(
      resolveBranding(
        { brand_names: {}, taglines: { "zh-CN": "ignored" } },
        "zh-CN",
        "Default product description",
        "en-US",
        CATALOG,
      ),
    ).toEqual({
      brandName: "Refraq",
      tagline: "Default product description",
    });
  });

  it("treats a primary-color-only site as unbranded", () => {
    expect(
      resolveBranding(
        { brand_names: {}, taglines: {} },
        "en-US",
        "Data Product Integration Platform",
        "en-US",
        CATALOG,
      ),
    ).toMatchObject({
      brandName: "Refraq",
      tagline: "Data Product Integration Platform",
    });
  });

  it("falls back through supplied default locale before catalog order", () => {
    expect(
      resolveBranding(
        {
          brand_names: { "en-US": "Acme", "zh-CN": "Acme China" },
          taglines: {},
        },
        "zh-CN",
        "ignored",
        "en-US",
        CATALOG,
      ).brandName,
    ).toBe("Acme China");

    expect(
      resolveBranding(
        { brand_names: { "en-US": "Acme" }, taglines: {} },
        "zh-CN",
        "ignored",
        "en-US",
        CATALOG,
      ).brandName,
    ).toBe("Acme");
  });

  it("uses the caller-supplied default locale, not an implicit env locale", () => {
    expect(
      resolveBranding(
        { brand_names: { "zh-CN": "Mingrui" }, taglines: {} },
        "en-US",
        "ignored",
        "zh-CN",
        ["en-US", "zh-CN"],
      ).brandName,
    ).toBe("Mingrui");
  });

  it("keeps a missing locale tagline empty on a branded site", () => {
    expect(
      resolveBranding(
        {
          brand_names: { "en-US": "Acme" },
          taglines: { "en-US": "Make data useful" },
        },
        "zh-CN",
        "Default product description",
        "en-US",
        CATALOG,
      ),
    ).toMatchObject({ brandName: "Acme", tagline: "" });
  });
});

describe("browserAssetUrl", () => {
  it("keeps branding assets on the browser origin", () => {
    expect(browserAssetUrl("/api/branding/assets/logo?v=abc")).toBe(
      "/api/branding/assets/logo?v=abc",
    );
    expect(browserAssetUrl("/branding/assets/logo?v=abc")).toBeNull();
    expect(browserAssetUrl("http://api:8000/branding/assets/logo")).toBeNull();
  });

  it("returns null when urls are absent", () => {
    expect(browserAssetUrl(null)).toBeNull();
  });
});

describe("showsRestoreAssetControl", () => {
  it("hides restore when the stored asset is the product seed", () => {
    expect(showsRestoreAssetControl("seed", false, false)).toBe(false);
  });

  it("shows restore for an operator overlay", () => {
    expect(showsRestoreAssetControl("user", false, false)).toBe(true);
    expect(showsRestoreAssetControl("seed", true, false)).toBe(true);
    expect(showsRestoreAssetControl("user", false, true)).toBe(false);
  });
});
