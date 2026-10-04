import { describe, expect, it } from "vitest";

import { cronPhrase } from "@/components/form/cronPhrase";

const t = (key: string, options?: Record<string, string | number>) =>
  options ? `${key}:${JSON.stringify(options)}` : key;

describe("cronPhrase", () => {
  it("phrases each schedule preset in the schedule zone and keeps the expression", () => {
    expect(cronPhrase("0 * * * *", t, "UTC")).toEqual({
      phrase: 'form.cron.hourly:{"minute":0,"zone":"UTC"}',
      raw: "0 * * * *",
    });
    expect(cronPhrase("0 2 * * *", t, "UTC")).toEqual({
      phrase: 'form.cron.daily:{"time":"02:00","zone":"UTC"}',
      raw: "0 2 * * *",
    });
    expect(cronPhrase("0 4 * * *", t, "Europe/Paris")).toEqual({
      phrase: 'form.cron.daily:{"time":"04:00","zone":"Europe/Paris"}',
      raw: "0 4 * * *",
    });
    expect(cronPhrase("0 2 * * 1", t, "UTC")).toEqual({
      phrase:
        'form.cron.weekly:{"weekday":"form.cron.dow.1","time":"02:00","zone":"UTC"}',
      raw: "0 2 * * 1",
    });
  });
});
