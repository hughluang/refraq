import { describe, expect, it } from "vitest";

import {
  classifyAccessProblem,
  columnsFromMatrix,
  combinationOverLimit,
  emptyRule,
  appendEditorCondition,
  isMaskedPresentation,
  literalOperand,
  matrixColumn,
  narrowBody,
  parseRule,
  presentCell,
  serializeRule,
  validateLadder,
  withheldNames,
  type RuleNode,
} from "@/features/entities/accessLogic";

describe("validateLadder", () => {
  it("requires clear first and unique keys", () => {
    expect(validateLadder([{ key: "clear", mode: "clear" }])).toBeNull();
    expect(
      validateLadder([
        { key: "clear", mode: "clear" },
        { key: "last4", mode: { type: "partial", keep_first: 0, keep_last: 4 } },
      ]),
    ).toBeNull();
    expect(validateLadder([])).toBe("empty");
    expect(validateLadder([{ key: "last4", mode: { type: "null" } }])).toBe("first");
    expect(
      validateLadder([
        { key: "clear", mode: "clear" },
        { key: "clear", mode: { type: "null" } },
      ]),
    ).toBe("duplicate");
  });
});

describe("profile matrix", () => {
  it("reads a blank cell as absent and writes only chosen levels", () => {
    expect(
      matrixColumn("att_note", [{ attribute_id: "att_sku", level: "clear" }]),
    ).toBe("");
    expect(matrixColumn("att_sku", [{ attribute_id: "att_sku", level: "last4" }])).toBe(
      "last4",
    );
    expect(
      columnsFromMatrix(["att_sku", "att_note"], { att_sku: "clear", att_note: "" }),
    ).toEqual([{ attribute_id: "att_sku", level: "clear" }]);
  });
});

describe("row rule editor", () => {
  it("round-trips a visual tree without a text DSL", () => {
    const tree: RuleNode = {
      kind: "and",
      children: [
        {
          kind: "leaf",
          op: "eq",
          attributeId: "att_region",
          operand: { kind: "subject_attr", key: "region" },
        },
        {
          kind: "not",
          child: {
            kind: "leaf",
            op: "is_null",
            attributeId: "att_sku",
            operand: { kind: "value", value: true },
          },
        },
      ],
    };
    const wire = serializeRule(tree);
    expect(wire).toEqual({
      and: [
        { eq: { attr: "att_region", subject_attr: "region" } },
        { not: { is_null: { attr: "att_sku", value: true } } },
      ],
    });
    expect(parseRule(wire)).toEqual(tree);
    expect(serializeRule(emptyRule())).toBeNull();
  });

  it("saves a flat AND and does not round-trip OR or NOT", () => {
    const east: RuleNode = {
      kind: "leaf",
      op: "eq",
      attributeId: "att_region",
      operand: { kind: "value", value: "EAST" },
    };
    const south: RuleNode = {
      kind: "leaf",
      op: "eq",
      attributeId: "att_region",
      operand: { kind: "value", value: "SOUTH" },
    };
    const saved = appendEditorCondition(appendEditorCondition(emptyRule(), east), south);
    expect(serializeRule(saved)).toEqual({
      and: [
        { eq: { attr: "att_region", value: "EAST" } },
        { eq: { attr: "att_region", value: "SOUTH" } },
      ],
    });
    const parsedOr = parseRule({
      or: [
        { eq: { attr: "att_region", value: "EAST" } },
        { eq: { attr: "att_region", value: "SOUTH" } },
      ],
    });
    expect(serializeRule(saved)).not.toEqual(serializeRule(parsedOr as RuleNode));
    const notRoot: RuleNode = { kind: "not", child: east };
    const wrapped = appendEditorCondition(notRoot, south);
    expect(wrapped.kind).toBe("and");
    const wire = serializeRule(wrapped);
    expect(wire !== null && "and" in wire).toBe(true);
  });
});

describe("combination warning", () => {
  it("flags subjects over the cap and a count past the limit", () => {
    expect(
      combinationOverLimit({
        combinations: 2,
        combination_limit: 64,
        subjects_over_limit: 1,
      }),
    ).toBe(true);
    expect(
      combinationOverLimit({
        combinations: 64,
        combination_limit: 64,
        subjects_over_limit: 0,
      }),
    ).toBe(false);
  });
});

describe("access problems", () => {
  it("names pending, write denial, generic conflict, and the cap", () => {
    expect(classifyAccessProblem("ENTITY_ACCESS_PENDING")).toBe("pending");
    expect(classifyAccessProblem("ENTITY_ACCESS_WRITE_DENIED")).toBe("write_denied");
    expect(classifyAccessProblem("ENTITY_ROW_CONFLICT")).toBe("conflict");
    expect(classifyAccessProblem("ENTITY_ACCESS_COMBINATION_LIMIT")).toBe(
      "combination_limit",
    );
    expect(classifyAccessProblem("ENTITY_NOT_FOUND")).toBe("other");
  });
});

describe("narrowing", () => {
  it("omits the field when unset and never sends an extra identity", () => {
    expect(narrowBody("none", "")).toEqual({});
    expect(narrowBody("user", "ignored")).toEqual({ narrow: { type: "user" } });
    expect(narrowBody("role", "role_1")).toEqual({
      narrow: { type: "role", id: "role_1" },
    });
  });
});

describe("presentCell", () => {
  it("shows withheld as inaccessible and null as empty", () => {
    expect(
      presentCell({
        name: "note",
        value: null,
        withheld: ["note"],
        masked: false,
        rowVarying: true,
        referenceHidden: false,
      }).kind,
    ).toBe("withheld");
    expect(
      presentCell({
        name: "note",
        value: null,
        withheld: [],
        masked: false,
        rowVarying: false,
        referenceHidden: false,
      }).kind,
    ).toBe("empty");
  });

  it("marks masks and hides an invisible reference target", () => {
    const masked = presentCell({
      name: "phone",
      value: "138****",
      withheld: [],
      masked: true,
      rowVarying: false,
      referenceHidden: false,
    });
    expect(masked.kind).toBe("value");
    expect(masked.marks).toContain("masked");
    expect(isMaskedPresentation([{ mode: "clear" }, { mode: { type: "partial" } }])).toBe(
      true,
    );
    expect(
      presentCell({
        name: "supplier",
        value: "sup_1",
        withheld: null,
        masked: false,
        rowVarying: false,
        referenceHidden: true,
      }).kind,
    ).toBe("inaccessible_record");
  });

  it("splits an in-list and treats is_null as a boolean", () => {
    expect(literalOperand("in", "a, b")).toEqual(["a", "b"]);
    expect(literalOperand("is_null", "true")).toBe(true);
    expect(literalOperand("eq", "west")).toBe("west");
  });

  it("reads the withheld marker field", () => {
    expect(withheldNames({ __withheld: ["note", 1] }, "__withheld")).toEqual(["note"]);
    expect(withheldNames({ sku: "A" }, null)).toEqual([]);
  });
});
