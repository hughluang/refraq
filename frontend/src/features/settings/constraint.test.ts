import { describe, expect, it } from "vitest";

import type { JsonSchemaProperty } from "@/lib/json-schema";
import {
  admitIntegerDraft,
  dirtyIntegerValues,
  integerFallback,
  storedIntegerViolatesConstraint,
} from "@/features/settings/constraint";

const range: JsonSchemaProperty = {
  type: "integer",
  minimum: 1,
  maximum: 168,
};

describe("admitIntegerDraft", () => {
  it("rejects an empty draft", () => {
    expect(admitIntegerDraft("", range)).toEqual({
      ok: false,
      reason: "empty",
    });
  });

  it("rejects a non-integer draft", () => {
    expect(admitIntegerDraft("12", range)).toEqual({
      ok: false,
      reason: "not_integer",
    });
    expect(admitIntegerDraft(12.5, range)).toEqual({
      ok: false,
      reason: "not_integer",
    });
  });

  it("rejects a draft outside the constraint", () => {
    expect(admitIntegerDraft(0, range)).toEqual({
      ok: false,
      reason: "below_min",
    });
    expect(admitIntegerDraft(169, range)).toEqual({
      ok: false,
      reason: "above_max",
    });
  });

  it("admits an integer inside the constraint", () => {
    expect(admitIntegerDraft(8, range)).toEqual({ ok: true, value: 8 });
  });
});

describe("integerFallback", () => {
  it("returns the nearest bound for a stored value outside the constraint", () => {
    expect(integerFallback(9999, range, 8)).toBe(168);
    expect(integerFallback(0, range, 8)).toBe(1);
  });
});

describe("storedIntegerViolatesConstraint", () => {
  it("flags a served value outside the current constraint", () => {
    expect(storedIntegerViolatesConstraint(9999, range)).toBe(true);
    expect(storedIntegerViolatesConstraint(8, range)).toBe(false);
  });
});

describe("dirtyIntegerValues", () => {
  const item = {
    key: "admin_session_ttl_hours",
    value: 8,
    constraint: range,
  };

  it("does not treat an empty or non-integer draft as dirty", () => {
    expect(dirtyIntegerValues([item], { [item.key]: "" })).toEqual({});
    expect(dirtyIntegerValues([item], { [item.key]: "12" })).toEqual({});
  });

  it("includes an admitted draft that differs from the served value", () => {
    expect(dirtyIntegerValues([item], { [item.key]: 12 })).toEqual({
      [item.key]: 12,
    });
  });
});
