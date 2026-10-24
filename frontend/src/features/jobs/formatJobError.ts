type Translate = (key: string) => string;

export type JobErrorLine = {
  /** Main line. Catalog copy when the code has one; otherwise `CODE: message`. */
  text: string;
  /** True when `problems.${code}` is in the catalog. */
  catalogued: boolean;
  /**
   * English occurrence text. Present only for a catalogued code, so the main
   * line stays localized and this text can sit in a disclosure.
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
  const occurrence = message?.trim() ? message.trim() : null;
  if (translated !== key) {
    return { text: translated, catalogued: true, occurrence };
  }
  return {
    text: `${code}: ${message ?? ""}`,
    catalogued: false,
    occurrence: null,
  };
}
