export type CronTranslate = (
  key: string,
  options?: Record<string, string | number>,
) => string;

/** Cadence presets the schedule form shows as a sentence. */
export type PresetCron =
  | "0 * * * *"
  | "0 2 * * *"
  | "0 4 * * *"
  | "0 2 * * 1";

export function cronPhrase(
  cron: PresetCron,
  t: CronTranslate,
): { phrase: string; raw: string } {
  switch (cron) {
    case "0 * * * *":
      return { phrase: t("form.cron.hourly", { minute: 0 }), raw: cron };
    case "0 2 * * *":
      return { phrase: t("form.cron.daily", { time: "02:00" }), raw: cron };
    case "0 4 * * *":
      return { phrase: t("form.cron.daily", { time: "04:00" }), raw: cron };
    case "0 2 * * 1":
      return {
        phrase: t("form.cron.weekly", {
          weekday: t("form.cron.dow.1"),
          time: "02:00",
        }),
        raw: cron,
      };
  }
}
