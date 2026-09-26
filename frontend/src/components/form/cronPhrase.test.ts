import { describe, expect, it } from "vitest";

import { cronPhrase } from "@/components/form/cronPhrase";

const t = (key: string, options?: Record<string, string | number>) =>
  options ? `${key}:${JSON.stringify(options)}` : key;

describe("cronPhrase", () => {
  it("phrases each schedule preset and keeps the expression", () => {
    expect(cronPhrase("0 * * * *", t)).toEqual({
      phrase: 'form.cron.hourly:{"minute":0}',
      raw: "0 * * * *",
    });
    expect(cronPhrase("0 2 * * *", t)).toEqual({
      phrase: 'form.cron.daily:{"time":"02:00"}',
      raw: "0 2 * * *",
    });
    expect(cronPhrase("0 4 * * *", t)).toEqual({
      phrase: 'form.cron.daily:{"time":"04:00"}',
      raw: "0 4 * * *",
    });
    expect(cronPhrase("0 2 * * 1", t)).toEqual({
      phrase:
        'form.cron.weekly:{"weekday":"form.cron.dow.1","time":"02:00"}',
      raw: "0 2 * * 1",
    });
  });
});
