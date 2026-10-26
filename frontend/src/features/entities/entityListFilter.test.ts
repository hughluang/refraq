import { describe, expect, it } from "vitest";

import {
  DEFAULT_ENTITY_LIST_STATUSES,
  entityListIsFiltered,
  entityListRequest,
  entityListShouldFetch,
  entitySaveTarget,
  entitySavedQuery,
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

  it("stores the name query, statuses, and tag ids, and leaves offset out", () => {
    const stored = entitySavedQuery({
      q: "  Alpha ",
      statuses: ["serving", "serving"],
      tagIds: ["tag_ledger", "tag_ledger"],
    });
    expect(stored).toEqual({
      q: "Alpha",
      status: ["serving"],
      tag_ids: ["tag_ledger"],
    });
    expect(Object.keys(stored)).not.toContain("offset");
  });

  it("saves into the applied filter, a matching filter, or a new one", () => {
    const current = entitySavedQuery({
      q: "Alpha",
      statuses: ["serving"],
      tagIds: ["tag_ledger"],
    });
    const other = entitySavedQuery({
      q: "",
      statuses: DEFAULT_ENTITY_LIST_STATUSES,
      tagIds: [],
    });
    expect(
      entitySaveTarget({
        appliedId: "sf_applied0001",
        stored: [{ id: "sf_match000001", query: other }],
        current,
      }),
    ).toEqual({ kind: "update", id: "sf_applied0001" });
    expect(
      entitySaveTarget({
        appliedId: null,
        stored: [{ id: "sf_match000001", query: current }],
        current,
      }),
    ).toEqual({ kind: "update", id: "sf_match000001" });
    expect(
      entitySaveTarget({
        appliedId: null,
        stored: [{ id: "sf_other000001", query: other }],
        current,
      }),
    ).toEqual({ kind: "create" });
  });
});
