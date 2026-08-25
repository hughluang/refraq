import { describe, expect, it } from "vitest";

import {
  contrastRatio,
  isHexColor,
  relativeLuminance,
  warnsInsufficientCustomContrast,
} from "@/features/branding/color";

describe("branding color helpers", () => {
  it("accepts only six-digit hex colors", () => {
    expect(isHexColor("#228be6")).toBe(true);
    expect(isHexColor("#fff")).toBe(false);
    expect(isHexColor("228be6")).toBe(false);
  });

  it("computes WCAG luminance endpoints", () => {
    expect(relativeLuminance("#000000")).toBe(0);
    expect(relativeLuminance("#ffffff")).toBe(1);
  });

  it("rejects non-hex input instead of treating it as black", () => {
    expect(() => relativeLuminance("not-a-color")).toThrow(
      /six-digit hex color/,
    );
    expect(() => contrastRatio("not-a-color")).toThrow(/six-digit hex color/);
  });

  it("uses the same luminance threshold as auto contrast", () => {
    expect(contrastRatio("#ffffff").foreground).toBe("#000000");
    expect(contrastRatio("#000000")).toEqual({
      foreground: "#ffffff",
      ratio: 21,
    });
  });

  it("warns only when a custom hex color fails 4.5:1", () => {
    expect(warnsInsufficientCustomContrast("", 3.56)).toBe(false);
    expect(warnsInsufficientCustomContrast("#228be6", 3.56)).toBe(true);
    expect(warnsInsufficientCustomContrast("#000000", 21)).toBe(false);
    expect(warnsInsufficientCustomContrast("not-a-color", 1)).toBe(false);
  });
});
