import { describe, expect, it } from "vitest";

import en from "@/locales/en-US/common.json";
import zh from "@/locales/zh-CN/common.json";
import { engineLabel, selectedEngine, SOURCE_ENGINES } from "./engineLabel";

describe("Source engine catalog", () => {
  it("allows MySQL and provides labels in both locales", () => {
    expect(SOURCE_ENGINES).toContain("mysql");
    expect(selectedEngine("mysql")).toBe("mysql");
    for (const copy of [en, zh]) {
      const translate = (key: string) => copy[key as keyof typeof copy] ?? key;
      expect(engineLabel(translate, "mysql")).toBe("MySQL");
    }
    expect(selectedEngine("unsupported")).toBeUndefined();
  });
});
