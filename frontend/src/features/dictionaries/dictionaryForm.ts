import type {
  Dictionary,
  DictionaryEntry,
  DictionaryEntryDraft,
  DictionaryFormValues,
} from "@/features/dictionaries/types";

export const DICTIONARY_NAME_MAX = 63;
export const DICTIONARY_DISPLAY_NAME_MAX = 256;
export const DICTIONARY_CODE_MAX = 64;
export const DICTIONARY_LABEL_MAX = 200;

const NAME_RE = /^[a-z][a-z0-9_]*$/;

export const EMPTY_DICTIONARY_ENTRY: DictionaryEntryDraft = {
  code: "",
  label: "",
  active: true,
};

export const EMPTY_DICTIONARY_FORM: DictionaryFormValues = {
  name: "",
  display_name: "",
  description: "",
  entries: [{ ...EMPTY_DICTIONARY_ENTRY }],
};

type Translate = (key: string, values?: Record<string, unknown>) => string;

export function dictionaryFormErrors(
  values: DictionaryFormValues,
  t: Translate,
): Record<string, string> {
  const errors: Record<string, string> = {};
  const name = values.name.trim();
  if (
    name.length === 0 ||
    name.length > DICTIONARY_NAME_MAX ||
    !NAME_RE.test(name)
  ) {
    errors.name = t("dictionaries.validation.name", { max: DICTIONARY_NAME_MAX });
  }
  const displayName = values.display_name.trim();
  if (
    displayName.length === 0 ||
    displayName.length > DICTIONARY_DISPLAY_NAME_MAX
  ) {
    errors.display_name = t("dictionaries.validation.displayName", {
      max: DICTIONARY_DISPLAY_NAME_MAX,
    });
  }
  if (values.entries.length === 0) {
    errors.entries = t("dictionaries.validation.entriesRequired");
  }
  const seen = new Set<string>();
  values.entries.forEach((entry, index) => {
    const code = entry.code.trim();
    if (code.length === 0 || code.length > DICTIONARY_CODE_MAX) {
      errors[`entries.${index}.code`] = t("dictionaries.validation.code", {
        max: DICTIONARY_CODE_MAX,
      });
    } else if (seen.has(code)) {
      errors[`entries.${index}.code`] = t("dictionaries.validation.codeDuplicate", {
        code,
      });
    } else {
      seen.add(code);
    }
    if (entry.label.length > DICTIONARY_LABEL_MAX) {
      errors[`entries.${index}.label`] = t("dictionaries.validation.label", {
        max: DICTIONARY_LABEL_MAX,
      });
    }
  });
  return errors;
}

export function entriesFromForm(
  entries: DictionaryEntryDraft[],
): DictionaryEntry[] {
  return entries.map((entry) => {
    const label = entry.label.trim();
    return {
      code: entry.code.trim(),
      ...(label ? { label } : {}),
      active: entry.active,
    };
  });
}

export function formFromDictionary(dictionary: Dictionary): DictionaryFormValues {
  return {
    name: dictionary.name,
    display_name: dictionary.display_name,
    description: dictionary.description ?? "",
    entries: (dictionary.entries ?? []).map((entry) => ({
      code: entry.code,
      label: entry.label ?? "",
      active: entry.active,
    })),
  };
}
