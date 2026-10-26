import { describe, expect, it } from "vitest";

import {
  DEFAULT_ENTITY_LIST_STATUSES,
  entityListIsFiltered,
  entityListRequest,
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

  it("sends repeated tag ids with the name query and status, and omits them when none are selected", () => {
    const opening = entityListRequest({
      q: "",
      statuses: DEFAULT_ENTITY_LIST_STATUSES,
      tagIds: [],
      limit: 50,
      offset: 0,
    });
    expect(opening).toEqual({
      status: ["not_serving", "serving"],
      limit: 50,
      offset: 0,
    });
    expect(opening).not.toHaveProperty("tag_id");

    expect(
      entityListRequest({
        q: "  Alpha ",
        statuses: ["serving"],
        tagIds: ["tag_ledger", "tag_tax"],
        limit: 50,
        offset: 50,
      }),
    ).toEqual({
      q: "Alpha",
      status: ["serving"],
      tag_id: ["tag_ledger", "tag_tax"],
      limit: 50,
      offset: 50,
    });

    expect(entityListIsFiltered("", DEFAULT_ENTITY_LIST_STATUSES, [])).toBe(
      false,
    );
    expect(
      entityListIsFiltered("", DEFAULT_ENTITY_LIST_STATUSES, ["tag_ledger"]),
    ).toBe(true);
    expect(
      entityListRequest({
        q: "",
        statuses: [],
        tagIds: ["tag_ledger"],
        limit: 50,
        offset: 0,
      }),
    ).toBeNull();
  });
});
