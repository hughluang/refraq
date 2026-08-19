import { describe, expect, it } from "vitest";

import {
  columnLabel,
  columnOptionLabel,
  isAutoDerivedJoin,
  mergeSelectedOption,
  retainSelectedOption,
  validateJoinDraft,
} from "@/features/sources/catalog-detail/joinEdges";

describe("validateJoinDraft", () => {
  it("requires evidence", () => {
    expect(
      validateJoinDraft({ evidence: "  ", fromId: "a", toId: "b" }),
    ).toEqual({ ok: false, messageKey: "catalog.joins.evidenceRequired" });
  });

  it("requires both column ids", () => {
    expect(
      validateJoinDraft({ evidence: "fk", fromId: "a", toId: null }),
    ).toEqual({ ok: false, messageKey: "catalog.joins.toColumnRequired" });
  });

  it("returns trimmed evidence on success", () => {
    expect(
      validateJoinDraft({ evidence: "  fk  ", fromId: "a", toId: "b" }),
    ).toEqual({ ok: true, evidence: "fk", fromId: "a", toId: "b" });
  });
});

describe("isAutoDerivedJoin", () => {
  it("is true only for foreign_key origin", () => {
    expect(isAutoDerivedJoin("foreign_key")).toBe(true);
    expect(isAutoDerivedJoin("human")).toBe(false);
    expect(isAutoDerivedJoin(null)).toBe(false);
  });
});

describe("column labels", () => {
  it("formats name and locator", () => {
    expect(columnOptionLabel("id", "col/id")).toBe("id · col/id");
    expect(
      columnLabel(
        [{ id: "1", name: "id", locator_key: "col/id" }],
        "1",
      ),
    ).toBe("id · col/id");
    expect(columnLabel([], "missing")).toBe("missing");
  });
});

describe("option merge", () => {
  it("keeps the selected option when search is empty", () => {
    expect(
      retainSelectedOption(
        [
          { value: "a", label: "A" },
          { value: "b", label: "B" },
        ],
        "b",
      ),
    ).toEqual([{ value: "b", label: "B" }]);
    expect(retainSelectedOption([{ value: "a", label: "A" }], null)).toEqual(
      [],
    );
  });

  it("prepends the selected option when it drops out of results", () => {
    const prev = [{ value: "sel", label: "Selected" }];
    expect(
      mergeSelectedOption([{ value: "x", label: "X" }], "sel", prev),
    ).toEqual([
      { value: "sel", label: "Selected" },
      { value: "x", label: "X" },
    ]);
    expect(
      mergeSelectedOption(
        [
          { value: "sel", label: "Selected" },
          { value: "x", label: "X" },
        ],
        "sel",
        prev,
      ),
    ).toEqual([
      { value: "sel", label: "Selected" },
      { value: "x", label: "X" },
    ]);
  });
});
