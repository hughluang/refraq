import { ApiError } from "@/lib/api";

type Translate = (key: string) => string;

/**
 * First-party copy for a Problem Code.
 * A missing `problems.${code}` entry keeps the English `detail`.
 * Anything that is not an API failure uses the caller's fallback.
 */
export function problemMessage(
  t: Translate,
  error: unknown,
  fallback: string,
): string {
  if (!(error instanceof ApiError)) return fallback;
  const key = `problems.${error.code}`;
  const translated = t(key);
  if (translated !== key) return translated;
  return error.detail;
}
