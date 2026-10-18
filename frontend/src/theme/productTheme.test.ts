import { DEFAULT_THEME, mergeMantineTheme } from "@mantine/core";
import { describe, expect, it } from "vitest";

import { appTheme } from "@/features/branding/theme";
import { productCssVariablesResolver, productTheme } from "@/theme/productTheme";
import { FEEDBACK_DELAY_MS, MOTION_MS } from "@/theme/tokens";

const TEN_SHADES = [
  "#f5f5f5",
  "#e0e0e0",
  "#bdbdbd",
  "#9e9e9e",
  "#757575",
  "#616161",
  "#424242",
  "#303030",
  "#212121",
  "#000000",
] as const;

describe("productTheme", () => {
  it("keeps the brand palette and adds product tokens", () => {
    const theme = mergeMantineTheme(DEFAULT_THEME, productTheme(TEN_SHADES));
    expect(theme.primaryColor).toBe("brand");
    expect(theme.colors.brand).toEqual([...TEN_SHADES]);
    expect(theme.defaultRadius).toBe("sm");
    expect(theme.radius.pill).toBe("999px");
    expect(theme.focusRing).toBe("auto");
    expect(theme.respectReducedMotion).toBe(true);
    expect(theme.other.feedbackDelayMs).toBe(FEEDBACK_DELAY_MS);
    expect(theme.components.Badge?.defaultProps?.variant).toBe("light");
    expect(theme.components.Tooltip?.defaultProps?.openDelay).toBe(FEEDBACK_DELAY_MS);
    expect(theme.components.ActionIcon?.defaultProps?.variant).toBe("subtle");
    expect(theme.components.Modal?.defaultProps?.transitionProps?.duration).toBe(
      MOTION_MS.base,
    );
    expect(appTheme(null).primaryColor).toBe("blue");
  });

  it("resolves tone variables differently for light and dark", () => {
    const theme = mergeMantineTheme(DEFAULT_THEME, productTheme(null));
    const vars = productCssVariablesResolver(theme);
    expect(vars.variables["--refraq-motion-fast"]).toBe("120ms");
    expect(vars.variables["--refraq-motion-base"]).toBe("200ms");
    expect(vars.variables["--refraq-motion-slow"]).toBe("300ms");
    expect(vars.light["--refraq-tone-running"]).toBe(theme.colors.cyan[6]);
    expect(vars.dark["--refraq-tone-running"]).toBe(theme.colors.cyan[4]);
    expect(vars.light["--refraq-tone-running"]).not.toBe(vars.dark["--refraq-tone-running"]);
  });

  it("sets dimmed, placeholder, and anchor text to at least 4.5:1", () => {
    const theme = mergeMantineTheme(DEFAULT_THEME, productTheme(null));
    const vars = productCssVariablesResolver(theme);
    const lightBody = "#ffffff";
    const darkBody = theme.colors.dark[7];
    const darkInput = theme.colors.dark[6];
    expect(vars.light["--mantine-color-dimmed"]).toBe(theme.colors.gray[7]);
    expect(vars.dark["--mantine-color-dimmed"]).toBe(theme.colors.dark[1]);
    expect(vars.light["--mantine-color-placeholder"]).toBe(theme.colors.gray[7]);
    expect(vars.dark["--mantine-color-placeholder"]).toBe(theme.colors.dark[1]);
    expect(vars.light["--mantine-color-anchor"]).toBe(theme.colors.blue[8]);
    expect(contrast(theme.colors.gray[7], lightBody)).toBeGreaterThanOrEqual(4.5);
    expect(contrast(theme.colors.dark[1], darkBody)).toBeGreaterThanOrEqual(4.5);
    expect(contrast(theme.colors.dark[1], darkInput)).toBeGreaterThanOrEqual(4.5);
    expect(contrast(theme.colors.blue[8], lightBody)).toBeGreaterThanOrEqual(4.5);
    expect(contrast(theme.colors.gray[6], lightBody)).toBeLessThan(4.5);
    expect(contrast(theme.colors.dark[2], darkBody)).toBeLessThan(4.5);
    expect(contrast(theme.colors.gray[5], lightBody)).toBeLessThan(4.5);
    expect(contrast(theme.colors.dark[3], darkInput)).toBeLessThan(4.5);
    expect(contrast(theme.colors.blue[7], lightBody)).toBeLessThan(4.5);
  });
});

function channel(hex: string, index: number): number {
  const value = Number.parseInt(hex.slice(1 + index * 2, 3 + index * 2), 16) / 255;
  return value <= 0.04045 ? value / 12.92 : ((value + 0.055) / 1.055) ** 2.4;
}

function contrast(foreground: string, background: string): number {
  const luminance = (hex: string) =>
    0.2126 * channel(hex, 0) + 0.7152 * channel(hex, 1) + 0.0722 * channel(hex, 2);
  const lighter = Math.max(luminance(foreground), luminance(background));
  const darker = Math.min(luminance(foreground), luminance(background));
  return (lighter + 0.05) / (darker + 0.05);
}
