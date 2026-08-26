import { describe, expect, it } from "vitest";

import {
  columnLabel,
  columnOptionLabel,
  joinDeleteErrorKey,
  joinRowActions,
  joinRowState,
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

describe("joinRowState", () => {
  it("classifies rejected, automated, and manual rows", () => {
    expect(
      joinRowState({ created_by_user_id: null, is_rejected: true }),
    ).toBe("rejected");
    expect(joinRowState({ created_by_user_id: null })).toBe("automated");
    expect(joinRowState({ created_by_user_id: "user_1" })).toBe("manual");
  });
});

describe("joinRowActions", () => {
  it("exposes restore only for rejected rows", () => {
    expect(joinRowActions("rejected")).toEqual({
      amend: false,
      reject: false,
      restore: true,
      delete: false,
    });
  });

  it("lets operators amend or reject any asserted row, and delete only manual ones", () => {
    expect(joinRowActions("automated")).toEqual({
      amend: true,
      reject: true,
      restore: false,
      delete: false,
    });
    expect(joinRowActions("manual")).toEqual({
      amend: true,
      reject: true,
      restore: false,
      delete: true,
    });
  });
});

describe("joinDeleteErrorKey", () => {
  it("maps known delete refusal codes to locale keys", () => {
    expect(joinDeleteErrorKey("JOIN_DELETE_AUTOMATIC")).toBe(
      "catalog.joins.error.deleteAutomatic",
    );
    expect(joinDeleteErrorKey("JOIN_REJECTED")).toBe(
      "catalog.joins.error.deleteRejected",
    );
  });

  it("returns null for unrelated codes", () => {
    expect(joinDeleteErrorKey("JOIN_ALREADY_DEFINED")).toBeNull();
    expect(joinDeleteErrorKey("CATALOG_JOIN_NOT_FOUND")).toBeNull();
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
