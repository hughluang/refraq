import { describe, expect, it } from "vitest";

import {
  DEFAULT_DICTIONARY_LIST_STATUSES,
  dictionaryListIsFiltered,
} from "@/features/dictionaries/dictionaryListFilter";

describe("dictionary list status filter", () => {
  it("treats an empty selection as off the default", () => {
    expect(dictionaryListIsFiltered("", [])).toBe(true);
  });

  it("treats the opening selection as the default", () => {
    expect(
      dictionaryListIsFiltered("", DEFAULT_DICTIONARY_LIST_STATUSES),
    ).toBe(false);
    expect(dictionaryListIsFiltered("", ["available"])).toBe(false);
  });

  it("treats a search term or any other status set as off default", () => {
    expect(
      dictionaryListIsFiltered("order", DEFAULT_DICTIONARY_LIST_STATUSES),
    ).toBe(true);
    expect(dictionaryListIsFiltered("", ["deprecated"])).toBe(true);
    expect(
      dictionaryListIsFiltered("", ["available", "deprecated"]),
    ).toBe(true);
  });
});
