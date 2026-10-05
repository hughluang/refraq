import cronstrue from "cronstrue/i18n";

export type CronTranslate = (
  key: string,
  options?: Record<string, string | number>,
) => string;

function cronstrueLocale(locale: string): string {
  return locale === "zh-CN" ? "zh_CN" : "en";
}

/** Friendly cadence sentence for a cron expression, or null when it cannot be parsed. */
export function describeCron(
  cron: string,
  locale: string,
  zone: string | null,
  t: CronTranslate,
): string | null {
  let text: string;
  try {
    text = cronstrue.toString(cron, {
      locale: cronstrueLocale(locale),
      use24HourTimeFormat: true,
      throwExceptionOnParseError: true,
    });
  } catch {
    return null;
  }
  return zone ? t("schedules.cadence.withZone", { text, zone }) : text;
}
