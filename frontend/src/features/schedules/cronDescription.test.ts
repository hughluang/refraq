import { describe, expect, it } from "vitest";

import { describeIntervalSeconds } from "@/features/schedules/cronCadence";
import { describeCron } from "@/features/schedules/cronDescription";
import en from "@/locales/en-US/common.json";
import zh from "@/locales/zh-CN/common.json";

function translator(messages: Record<string, string>) {
  return (key: string, options?: Record<string, string | number>) =>
    (messages[key] ?? key).replace(/\{\{(\w+)\}\}/g, (_, name: string) =>
      String(options?.[name] ?? ""),
    );
}

const tZh = translator(zh as Record<string, string>);
const tEn = translator(en as Record<string, string>);

const cases: Array<[string, string]> = [
  ["0 4 * * *", "Daily at 04:00"],
  ["0 2 * * 1-3", "Every Mon–Wed at 02:00"],
  ["0 2 * * 1,2", "Every Mon, Tue at 02:00"],
  ["0 2 * * 1,3,5", "Every Mon, Wed, Fri at 02:00"],
  ["0 2 * * 0,6", "Every Sun, Sat at 02:00"],
  ["0 2 * * 7", "Every Sun at 02:00"],
  ["0 9 1 * *", "Monthly on day 1 at 09:00"],
  ["0 9 1,15 * *", "Monthly on day 1, 15 at 09:00"],
  ["0 9 1 1,7 *", "Yearly in Jan, Jul, day 1 at 09:00"],
  ["0 9,18 * * *", "Daily at 09:00, 18:00"],
  ["0,30 9 * * *", "Daily at 09:00, 09:30"],
  ["*/15 * * * *", "Every 15 min"],
  ["* * * * *", "Every 1 min"],
  ["0 */2 * * *", "Every 2 h on the hour"],
  ["30 */2 * * *", "Every 2 h at :30"],
  ["30 * * * *", "hourly at :30"],
  ["*/15 9-17 * * 1-5", "Every Mon–Fri 09:00–17:59 Every 15 min"],
];

describe("describeCron", () => {
  it.each(cases)("%s", (cron, enText) => {
    expect(describeCron(cron, "en-US", tEn)).toBe(enText);
  });

  it("builds zh-CN sentences from the locale file with Monday first", () => {
    const zhMessages = zh as Record<string, string>;
    const daily = describeCron("0 4 * * *", "zh-CN", tZh);
    expect(daily).toBe(`${zhMessages["schedules.cadence.phrase.scope.daily"]} 04:00`);
    const weekend = describeCron("0 2 * * 0,6", "zh-CN", tZh);
    expect(weekend?.indexOf("6")).toBe(-1);
    expect(weekend).toMatch(/02:00$/);
    expect(describeCron("0 */2 * * *", "zh-CN", tZh)).toContain("2");
  });

  it("lists up to four times and falls back beyond", () => {
    expect(describeCron("0 1,2,3,4 * * *", "en-US", tEn)).toBe(
      "Daily at 01:00, 02:00, 03:00, 04:00",
    );
    const five = describeCron("0 1,2,3,4,5 * * *", "en-US", tEn);
    expect(five).not.toBeNull();
    expect(five).not.toContain("01:00, 02:00, 03:00, 04:00, 05:00");
    expect(five).toContain("05:00");
  });

  it("falls back to cronstrue for shapes it does not model", () => {
    expect(describeCron("*/5 */2 * * *", "en-US", tEn)).toContain("5 minutes");
  });

  it("returns null for invalid expressions", () => {
    expect(describeCron("nope", "en-US", tEn)).toBeNull();
  });
});

describe("describeIntervalSeconds", () => {
  it("uses the largest even unit", () => {
    expect(describeIntervalSeconds(5400, tZh)).toContain("90");
    expect(describeIntervalSeconds(3600, tEn)).toBe("Every 1 h");
    expect(describeIntervalSeconds(7200, tEn)).toBe("Every 2 h");
    expect(describeIntervalSeconds(45, tEn)).toBe("Every 45 s");
  });
});
