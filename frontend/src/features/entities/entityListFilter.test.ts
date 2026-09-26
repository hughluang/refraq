import { describe, expect, it } from "vitest";

import {
  DEFAULT_ENTITY_LIST_STATUSES,
  entityListIsFiltered,
  entityListShouldFetch,
} from "@/features/entities/entityListFilter";

describe("entity list status filter", () => {
  it("does not request when nothing is selected", () => {
    expect(entityListShouldFetch([])).toBe(false);
    expect(entityListIsFiltered("", [])).toBe(true);
  });

  it("treats the opening selection as the default", () => {
    expect(entityListShouldFetch(DEFAULT_ENTITY_LIST_STATUSES)).toBe(true);
    expect(entityListIsFiltered("", DEFAULT_ENTITY_LIST_STATUSES)).toBe(false);
    expect(entityListIsFiltered("", ["serving", "not_serving"])).toBe(false);
  });

  it("treats a search term or any other status set as off default", () => {
    expect(entityListIsFiltered("material", DEFAULT_ENTITY_LIST_STATUSES)).toBe(
      true,
    );
    expect(entityListIsFiltered("", ["deprecated"])).toBe(true);
    expect(
      entityListIsFiltered("", ["not_serving", "serving", "deprecated"]),
    ).toBe(true);
    expect(entityListShouldFetch(["deprecated"])).toBe(true);
  });
});
