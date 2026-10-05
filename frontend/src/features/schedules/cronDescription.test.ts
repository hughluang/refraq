import { describe, expect, it } from "vitest";

import { describeCron } from "@/features/schedules/cronDescription";

const t = (key: string, options?: Record<string, string | number>) =>
  `${key}:${options?.text}|${options?.zone}`;

describe("describeCron", () => {
  it("describes in zh-CN", () => {
    const out = describeCron("0 3 * * *", "zh-CN", null, t);
    expect(out).toContain("03:00");
    expect(out).not.toContain("At ");
  });

  it("describes in en", () => {
    expect(describeCron("0 3 * * *", "en-US", null, t)).toBe("At 03:00");
  });

  it("appends the zone through i18n", () => {
    expect(describeCron("0 3 * * *", "en-US", "Asia/Shanghai", t)).toBe(
      "schedules.cadence.withZone:At 03:00|Asia/Shanghai",
    );
  });

  it("returns null for invalid expressions", () => {
    expect(describeCron("nope", "en-US", null, t)).toBeNull();
  });
});
