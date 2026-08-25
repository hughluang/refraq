import { DEFAULT_THEME, mergeMantineTheme } from "@mantine/core";
import { describe, expect, it } from "vitest";

import { appTheme } from "@/features/branding/theme";

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

describe("appTheme", () => {
  it("keeps the default Mantine palette when branding has no custom shades", () => {
    const theme = mergeMantineTheme(DEFAULT_THEME, appTheme(null));
    expect(theme.primaryColor).toBe("blue");
    expect(theme.colors.blue).toBeDefined();
  });

  it("adds brand shades without dropping default colors", () => {
    const theme = mergeMantineTheme(DEFAULT_THEME, appTheme(TEN_SHADES));
    expect(theme.primaryColor).toBe("brand");
    expect(theme.colors.brand).toEqual([...TEN_SHADES]);
    expect(theme.colors.blue).toBeDefined();
  });
});
