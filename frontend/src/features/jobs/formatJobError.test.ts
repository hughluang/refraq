import { describe, expect, it } from "vitest";

import en from "@/locales/en-US/common.json";
import zh from "@/locales/zh-CN/common.json";
import { formatJobError } from "@/features/jobs/formatJobError";

const LOCK = "structure Kind execution lock held for source src_fe7a680d0bb9";

describe("formatJobError", () => {
  it.each([
    ["en-US", en],
    ["zh-CN", zh],
  ] as const)("%s uses the catalog sentence for JOB_ALREADY_ACTIVE", (_locale, catalog) => {
    const t = (key: string) => catalog[key as keyof typeof catalog] ?? key;
    const line = formatJobError(t, "JOB_ALREADY_ACTIVE", LOCK);
    expect(line.catalogued).toBe(true);
    expect(line.text).toBe(t("problems.JOB_ALREADY_ACTIVE"));
    expect(line.text).not.toBe(LOCK);
    expect(line.text).not.toContain("JOB_ALREADY_ACTIVE");
    expect(line.text).not.toContain("Kind execution lock");
    expect(line.occurrence).toBe(LOCK);
  });

  it("drops an occurrence that repeats the English catalog sentence", () => {
    const t = (key: string) => zh[key as keyof typeof zh] ?? key;
    const sentence = en["problems.JOB_ALREADY_ACTIVE" as keyof typeof en];
    const line = formatJobError(t, "JOB_ALREADY_ACTIVE", sentence);
    expect(line.catalogued).toBe(true);
    expect(line.text).toBe(t("problems.JOB_ALREADY_ACTIVE"));
    expect(line.text).not.toBe(sentence);
    expect(line.occurrence).toBeNull();
  });

  it("keeps the code and English text when the catalog has no entry", () => {
    const t = (key: string) => key;
    const line = formatJobError(t, "JOB_COLLECT_FAILED", "connector aborted");
    expect(line.catalogued).toBe(false);
    expect(line.text).toBe("JOB_COLLECT_FAILED: connector aborted");
    expect(line.occurrence).toBeNull();
  });
});
