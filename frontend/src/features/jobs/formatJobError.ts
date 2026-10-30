import { repeatsContractSentence } from "@/lib/problem";

type Translate = (key: string) => string;

export type JobErrorLine = {
  /** Main line. Catalog copy when the code has one; otherwise `CODE: message`. */
  text: string;
  /** True when `problems.${code}` is in the catalog. */
  catalogued: boolean;
  /**
   * Server text that is not the English catalog sentence for this code.
   * Present only for a catalogued code, so the main line stays localized
   * and this text can sit in a disclosure.
   */
  occurrence: string | null;
};

/** Operator-facing Job failure line. Unknown codes keep the English occurrence. */
export function formatJobError(
  t: Translate,
  code: string,
  message: string | null,
): JobErrorLine {
  const key = `problems.${code}`;
  const translated = t(key);
  const trimmed = message?.trim() ? message.trim() : null;
  const occurrence =
    trimmed && !repeatsContractSentence(code, trimmed) ? trimmed : null;
  if (translated !== key) {
    return { text: translated, catalogued: true, occurrence };
  }
  return {
    text: `${code}: ${message ?? ""}`,
    catalogued: false,
    occurrence: null,
  };
}
