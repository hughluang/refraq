import { describe, expect, it } from "vitest";

import {
  dictionaryFormErrors,
  entriesFromForm,
  formFromDictionary,
} from "@/features/dictionaries/dictionaryForm";
import type { Dictionary, DictionaryFormValues } from "@/features/dictionaries/types";

const t = (key: string) => key;

function values(
  overrides: Partial<DictionaryFormValues> = {},
): DictionaryFormValues {
  return {
    name: "order_status",
    display_name: "Order status",
    description: "",
    entries: [{ code: "open", label: "Open", active: true }],
    ...overrides,
  };
}

describe("dictionaryFormErrors", () => {
  it("accepts a legal name and one code", () => {
    expect(dictionaryFormErrors(values(), t)).toEqual({});
  });

  it("rejects a blank code list and a duplicated code", () => {
    expect(dictionaryFormErrors(values({ name: "Order" }), t).name).toBe(
      "dictionaries.validation.name",
    );
    const duplicate = dictionaryFormErrors(
      values({
        entries: [
          { code: "open", label: "", active: true },
          { code: " open ", label: "", active: true },
        ],
      }),
      t,
    );
    expect(duplicate["entries.1.code"]).toBe(
      "dictionaries.validation.codeDuplicate",
    );
  });
});

describe("entriesFromForm", () => {
  it("drops a blank label and trims the code", () => {
    expect(
      entriesFromForm([{ code: " open ", label: "  ", active: false }]),
    ).toEqual([{ code: "open", active: false }]);
  });
});

describe("formFromDictionary", () => {
  it("keeps an empty label as an empty string", () => {
    const dictionary = {
      id: "cl_1",
      name: "order_status",
      display_name: "Order status",
      description: null,
      revision: 1,
      deprecated_at: null,
      entry_count: 1,
      entries: [{ code: "open", active: true }],
      created_at: "2026-01-01T00:00:00Z",
      updated_at: "2026-01-01T00:00:00Z",
    } satisfies Dictionary;
    expect(formFromDictionary(dictionary).entries).toEqual([
      { code: "open", label: "", active: true },
    ]);
  });

  it("leaves a missing entry list empty", () => {
    const dictionary = {
      id: "cl_1",
      name: "order_status",
      display_name: "Order status",
      description: null,
      revision: 1,
      deprecated_at: null,
      entry_count: 0,
      created_at: "2026-01-01T00:00:00Z",
      updated_at: "2026-01-01T00:00:00Z",
    } satisfies Dictionary;
    const form = formFromDictionary(dictionary);
    expect(form.entries).toEqual([]);
    expect(dictionaryFormErrors(form, t).entries).toBe(
      "dictionaries.validation.entriesRequired",
    );
  });
});
