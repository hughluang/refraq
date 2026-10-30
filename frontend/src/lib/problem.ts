import en from "@/locales/en-US/common.json";

import { ApiError } from "@/lib/api";

const enMessages = en as Record<string, string>;

/**
 * True when `message` is the English catalog sentence for `problems.${code}`.
 * That sentence is already the localized main line, so it is not an extra occurrence.
 */
export function repeatsContractSentence(code: string, message: string): boolean {
  const sentence = enMessages[`problems.${code}`];
  return typeof sentence === "string" && message.trim() === sentence;
}

type Translate = (key: string, options?: Record<string, string>) => string;

/**
 * First-party copy for a Problem Code.
 * Codes other than `TAG_IN_USE` use `problems.${code}`, or `problems.unknown`
 * when that entry is missing. Server `detail` is never the main message.
 * `TAG_IN_USE` states both counts when `entity_count` and `channel_count`
 * are non-negative integers, including zero. Otherwise it uses the sentence
 * without counts.
 * Anything that is not an API failure uses the caller's fallback.
 */
export function problemMessage(
  t: Translate,
  error: unknown,
  fallback: string,
): string {
  if (!(error instanceof ApiError)) return fallback;
  if (error.code === "TAG_IN_USE") return tagInUseMessage(t, error);
  const key = `problems.${error.code}`;
  const translated = t(key);
  if (translated !== key) return translated;
  return t("problems.unknown");
}

function nonNegativeInt(value: unknown): number | null {
  if (typeof value !== "number" || !Number.isInteger(value) || value < 0) return null;
  return value;
}

function tagInUseMessage(t: Translate, error: ApiError): string {
  const entityCount = nonNegativeInt(error.extensions.entity_count);
  const channelCount = nonNegativeInt(error.extensions.channel_count);
  if (entityCount !== null && channelCount !== null) {
    return t("problems.TAG_IN_USE", {
      entity_count: String(entityCount),
      channel_count: String(channelCount),
    });
  }
  return t("problems.TAG_IN_USE_BARE");
}
