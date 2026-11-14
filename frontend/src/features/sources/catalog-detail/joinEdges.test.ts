import { describe, expect, it } from "vitest";

import {
  joinRowActions,
  joinRowState,
  mergeSelectedOption,
  objectRefFromColumnLocator,
} from "@/features/sources/catalog-detail/joinEdges";

describe("joinRowState", () => {
  it("classifies rejected, automated, and manual rows", () => {
    expect(joinRowState({ created_by_user_id: null, is_rejected: true })).toBe("rejected");
    expect(joinRowState({ created_by_user_id: null })).toBe("automated");
    expect(joinRowState({ created_by_user_id: "user_1" })).toBe("manual");
  });
});

describe("joinRowActions", () => {
  it("exposes restore only for rejected rows", () => {
    expect(joinRowActions("rejected")).toEqual({ amend: false, reject: false, restore: true, delete: false });
  });

  it("lets operators amend or reject any asserted row, and delete only manual ones", () => {
    expect(joinRowActions("automated")).toEqual({ amend: true, reject: true, restore: false, delete: false });
    expect(joinRowActions("manual")).toEqual({ amend: true, reject: true, restore: false, delete: true });
  });
});

describe("objectRefFromColumnLocator", () => {
  it("derives the object locator from a column locator", () => {
    expect(objectRefFromColumnLocator("col/postgresql/mes-a/public/table/orders/column/id"))
      .toBe("obj/postgresql/mes-a/public/table/orders");
  });

  it("does not invent links for malformed or missing locators", () => {
    for (const locator of [null, "col/too/short", "obj/postgresql/mes/public/table/t", "col/pg/src/public/table/t/field/id", "col/pg/src/public/table/t/column/id/extra", "col/pg//public/table/t/column/id"]) {
      expect(objectRefFromColumnLocator(locator)).toBeNull();
    }
  });
});

describe("option merge", () => {
  it("keeps selection when search is empty", () => {
    expect(mergeSelectedOption([], "b", [{ value: "a", label: "A" }, { value: "b", label: "B" }])).toEqual([{ value: "b", label: "B" }]);
    expect(mergeSelectedOption([], null, [{ value: "a", label: "A" }])).toEqual([]);
  });

  it("prepends the selected option when it drops out of results", () => {
    const prev = [{ value: "sel", label: "Selected" }];
    expect(mergeSelectedOption([{ value: "x", label: "X" }], "sel", prev)).toEqual([
      { value: "sel", label: "Selected" }, { value: "x", label: "X" },
    ]);
    expect(mergeSelectedOption([{ value: "sel", label: "Selected" }, { value: "x", label: "X" }], "sel", prev)).toEqual([
      { value: "sel", label: "Selected" }, { value: "x", label: "X" },
    ]);
  });
});
