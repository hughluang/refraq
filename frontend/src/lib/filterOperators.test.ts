import { describe, expect, it } from "vitest";

import {
  availableFilterOperators,
  filterOperatorLabelKey,
  getFilterOperatorMeta,
  transitionOperatorValues,
} from "./filterOperators";

describe("filterOperators", () => {
  it("orders allowed operators canonically and preserves unknown extras", () => {
    expect(availableFilterOperators(["is_not_null", "gte", "eq", "between", "custom"])).toEqual([
      "eq",
      "gte",
      "between",
      "is_not_null",
      "custom",
    ]);
    expect(availableFilterOperators(null)).toEqual([]);
  });

  it("exposes arity, value domain, and label keys", () => {
    expect(getFilterOperatorMeta("is_not_null")).toEqual({
      name: "is_not_null",
      arity: "none",
      valueDomain: "field",
      labelKey: "filter.op.is_not_null",
    });
    expect(getFilterOperatorMeta("between").arity).toBe("range");
    expect(getFilterOperatorMeta("not_in").arity).toBe("array");
    expect(getFilterOperatorMeta("has_key").valueDomain).toBe("string");
    expect(getFilterOperatorMeta("json_contains").valueDomain).toBe("json");
    expect(filterOperatorLabelKey("gte")).toBe("filter.op.gte");
  });

  it("transitions values cleanly across arities and domains", () => {
    expect(transitionOperatorValues("eq", "gte", ["42"])).toEqual(["42"]);
    expect(transitionOperatorValues("eq", "between", ["10"])).toEqual(["10", ""]);
    expect(transitionOperatorValues("between", "lte", ["10", "20"])).toEqual(["10"]);
    expect(transitionOperatorValues("eq", "is_not_null", ["42"])).toEqual([]);
    expect(transitionOperatorValues("eq", "json_contains", ["42"])).toEqual([""]);
    expect(transitionOperatorValues("eq", "in", ["a"])).toEqual(["a"]);
  });
});
