import cronstrue from "cronstrue/i18n";

import {
  describeCronCadence,
  type CronTranslate,
} from "@/features/schedules/cronCadence";

function cronstrueLocale(locale: string): string {
  return locale === "zh-CN" ? "zh_CN" : "en";
}

/** Friendly cadence sentence for a cron expression, or null when it cannot be parsed. */
export function describeCron(
  cron: string,
  locale: string,
  t: CronTranslate,
): string | null {
  try {
    cronstrue.toString(cron, { throwExceptionOnParseError: true });
  } catch {
    return null;
  }
  const own = describeCronCadence(cron, locale, t);
  if (own !== null) return own;
  try {
    return cronstrue.toString(cron, {
      locale: cronstrueLocale(locale),
      use24HourTimeFormat: true,
      throwExceptionOnParseError: true,
    });
  } catch {
    return null;
  }
}
