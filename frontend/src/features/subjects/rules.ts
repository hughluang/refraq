export const SUBJECT_KEY_MAX_LENGTH = 63;
export const SUBJECT_NAME_MAX_LENGTH = 256;
export const STRING_VALUE_MAX_LENGTH = 256;
export const SUBJECT_VALUES_MAX = 256;

const KEY_RE = /^[a-z][a-z0-9_]*$/;
const DATE_RE = /^\d{4}-\d{2}-\d{2}$/;
const BIGINT_MIN = -(BigInt(2) ** BigInt(63));
const BIGINT_MAX = BigInt(2) ** BigInt(63) - BigInt(1);

export type SubjectValueType =
  | "string"
  | "integer"
  | "date"
  | "dictionary"
  | "user";

export type SubjectKeyError = "required" | "charset";
export type SubjectNameError = "required" | "tooLong";

export function subjectKeyError(value: string): SubjectKeyError | null {
  if (!value) return "required";
  if (!KEY_RE.test(value) || value.length > SUBJECT_KEY_MAX_LENGTH) {
    return "charset";
  }
  return null;
}

export function subjectNameError(value: string): SubjectNameError | null {
  const name = value.trim();
  if (!name) return "required";
  if (name.length > SUBJECT_NAME_MAX_LENGTH) return "tooLong";
  return null;
}

export type ValueDraft = {
  key: string;
  valueType: SubjectValueType;
  multiValue: boolean;
  texts: string[];
};

export type SubjectValueReason =
  | "single"
  | "tooMany"
  | "integer"
  | "date"
  | "string";

export type SubjectValueIssue = {
  key: string;
  reason: SubjectValueReason;
};

export type EncodedSubjectValues = Record<string, Array<string | number>>;

function isIsoDate(value: string): boolean {
  if (!DATE_RE.test(value)) return false;
  const [year, month, day] = value.split("-").map(Number);
  const date = new Date(Date.UTC(year, month - 1, day));
  return (
    date.getUTCFullYear() === year &&
    date.getUTCMonth() === month - 1 &&
    date.getUTCDate() === day
  );
}

function distinct(items: readonly string[]): string[] {
  return [...new Set(items)];
}

/** Blank entries are dropped. A key with no remaining values is omitted. */
export function encodeSubjectDrafts(
  drafts: readonly ValueDraft[],
):
  | { ok: true; values: EncodedSubjectValues }
  | { ok: false; issue: SubjectValueIssue } {
  const values: EncodedSubjectValues = {};
  for (const draft of drafts) {
    const texts = distinct(
      draft.texts.map((item) => item.trim()).filter((item) => item !== ""),
    );
    if (texts.length === 0) continue;
    if (!draft.multiValue && texts.length > 1) {
      return { ok: false, issue: { key: draft.key, reason: "single" } };
    }
    if (texts.length > SUBJECT_VALUES_MAX) {
      return { ok: false, issue: { key: draft.key, reason: "tooMany" } };
    }
    const encoded: Array<string | number> = [];
    for (const text of texts) {
      if (draft.valueType === "integer") {
        if (!/^-?\d+$/.test(text)) {
          return { ok: false, issue: { key: draft.key, reason: "integer" } };
        }
        const parsed = BigInt(text);
        const safeMax = BigInt(Number.MAX_SAFE_INTEGER);
        if (
          parsed < BIGINT_MIN ||
          parsed > BIGINT_MAX ||
          parsed > safeMax ||
          parsed < -safeMax
        ) {
          return { ok: false, issue: { key: draft.key, reason: "integer" } };
        }
        encoded.push(Number(text));
        continue;
      }
      if (draft.valueType === "date" && !isIsoDate(text)) {
        return { ok: false, issue: { key: draft.key, reason: "date" } };
      }
      if (
        draft.valueType === "string" &&
        text.length > STRING_VALUE_MAX_LENGTH
      ) {
        return { ok: false, issue: { key: draft.key, reason: "string" } };
      }
      encoded.push(text);
    }
    values[draft.key] = encoded;
  }
  return { ok: true, values };
}
