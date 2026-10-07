import { describe, expect, it } from "vitest";

import {
  accessChainSteps,
  accessGuide,
  accessKeyFromName,
  classifyAccessProblem,
  ruleEditorHint,
  ruleOperandKinds,
  ruleRejectionKey,
  columnsFromMatrix,
  combinationBudgetVisible,
  formatGrantLine,
  isAccessKey,
  isMaskedPresentation,
  ladderIssueKey,
  laddersClearOnly,
  levelOptionLabel,
  levelReferrers,
  literalOperand,
  matrixColumn,
  narrowBody,
  parseStoredRule,
  presentCell,
  profileGrantCount,
  profileIsAllClear,
  ruleLeafPhrase,
  ruleOpLabelKey,
  sameProfileColumns,
  serializeRule,
  validateLadder,
  viewsNeedAttention,
  viewsStatusKey,
  withheldNames,
  type RuleLeaf,
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
  const leaf = (value: string): RuleLeaf => ({
    kind: "leaf",
    op: "eq",
    attributeId: "att_region",
    operand: { kind: "value", value },
  });

  it("saves a flat AND of leaves and nothing for an empty editor", () => {
    const empty: RuleNode = { kind: "and", children: [] };
    expect(serializeRule(empty)).toBeNull();
    const saved: RuleNode = {
      kind: "and",
      children: [
        leaf("EAST"),
        {
          kind: "leaf",
          op: "is_null",
          attributeId: "att_sku",
          operand: { kind: "subject_attr", key: "region" },
        },
      ],
    };
    expect(serializeRule(saved)).toEqual({
      and: [
        { eq: { attr: "att_region", value: "EAST" } },
        { is_null: { attr: "att_sku", subject_attr: "region" } },
      ],
    });
  });
});

describe("views status", () => {
  it("does not call a missing serving table ready", () => {
    expect(
      viewsStatusKey({ head_version_id: null, views: { state: "ready" } }),
    ).toBe("entities.access.views.noHead");
    expect(
      viewsStatusKey({ head_version_id: "ver_1", views: { state: "ready" } }),
    ).toBe("entities.access.views.ready");
    expect(
      viewsStatusKey({ head_version_id: "ver_1", views: { state: "pending" } }),
    ).toBe("entities.access.views.pending");
  });
});

describe("access problems", () => {
  it("names pending and the cap", () => {
    expect(classifyAccessProblem("ENTITY_ACCESS_PENDING")).toBe("pending");
    expect(classifyAccessProblem("ENTITY_ACCESS_COMBINATION_LIMIT")).toBe(
      "combination_limit",
    );
    expect(classifyAccessProblem("ENTITY_NOT_FOUND")).toBe("other");
  });
});

describe("row rule operands", () => {
  it("offers a person's attribute only for is-one-of", () => {
    expect(ruleOperandKinds("eq", "string")).toEqual(["value"]);
    expect(ruleOperandKinds("in", "string")).toEqual(["value", "subject_attr"]);
    expect(ruleEditorHint("eq", "string")).toBe("entities.access.rule.hint.subjectAttr");
    expect(ruleEditorHint("in", "string")).toBeNull();
  });

  it("offers the current user only for equals on a user column", () => {
    expect(ruleOperandKinds("eq", "user")).toEqual(["value", "subject_id"]);
    expect(ruleOperandKinds("ne", "user")).toEqual(["value", "subject_id"]);
    expect(ruleOperandKinds("eq", "string")).not.toContain("subject_id");
    expect(ruleOperandKinds("in", "user")).not.toContain("subject_id");
    expect(ruleEditorHint("in", "user")).toBe("entities.access.rule.hint.subjectId");
  });

  it("offers relative time only for before-or-after on a date or timestamp", () => {
    expect(ruleOperandKinds("lt", "date")).toEqual(["value", "rel_time"]);
    expect(ruleOperandKinds("gte", "timestamp")).toEqual(["value", "rel_time"]);
    expect(ruleOperandKinds("eq", "date")).toEqual(["value"]);
    expect(ruleOperandKinds("lt", "string")).toEqual(["value"]);
    expect(ruleEditorHint("in", "timestamp")).toBe("entities.access.rule.hint.relTime");
  });

  it("maps rule rejection details to copy keys and hides other paths", () => {
    expect(ruleRejectionKey("$.and[0].eq: subject_attr is only valid for in")).toBe(
      "entities.access.rule.reject.subjectAttr",
    );
    expect(ruleRejectionKey("$.and[0].lt: subject_id is true and only eq or ne")).toBe(
      "entities.access.rule.reject.subjectIdOp",
    );
    expect(ruleRejectionKey("$.eq: subject_id compares only a user attribute")).toBe(
      "entities.access.rule.reject.subjectIdType",
    );
    expect(
      ruleRejectionKey("$.gt: rel_time is only valid for lt, lte, gt, and gte"),
    ).toBe("entities.access.rule.reject.relTimeOp");
    expect(ruleRejectionKey("$.lt: rel_time compares only date or timestamp")).toBe(
      "entities.access.rule.reject.relTimeType",
    );
    expect(ruleRejectionKey("$.and[0].eq: unknown attribute 'att_x'")).toBe(
      "entities.access.rule.reject.generic",
    );
    expect(ruleRejectionKey("write without read")).toBeNull();
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
        referenceHidden: false,
      }).kind,
    ).toBe("withheld");
    expect(
      presentCell({
        name: "note",
        value: null,
        withheld: [],
        referenceHidden: false,
      }).kind,
    ).toBe("empty");
  });

  it("hides an invisible reference target and reads mask presentation", () => {
    const masked = presentCell({
      name: "phone",
      value: "138****",
      withheld: [],
      referenceHidden: false,
    });
    expect(masked.kind).toBe("value");
    expect(isMaskedPresentation([{ mode: "clear" }, { mode: { type: "partial" } }])).toBe(
      true,
    );
    expect(
      presentCell({
        name: "supplier",
        value: "sup_1",
        withheld: null,
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

describe("access console phrasing", () => {
  it("hides a quiet combination budget and surfaces one near the cap", () => {
    expect(
      combinationBudgetVisible({
        combinations: 0,
        combination_limit: 64,
        subjects_over_limit: 0,
      }),
    ).toBe(false);
    expect(
      combinationBudgetVisible({
        combinations: 52,
        combination_limit: 64,
        subjects_over_limit: 0,
      }),
    ).toBe(true);
    expect(
      combinationBudgetVisible({
        combinations: 0,
        combination_limit: 64,
        subjects_over_limit: 1,
      }),
    ).toBe(true);
  });

  it("asks for attention only when views are not serving", () => {
    expect(viewsNeedAttention({ head_version_id: null, views: { state: "ready" } })).toBe(
      true,
    );
    expect(viewsNeedAttention({ head_version_id: "ver_1", views: { state: "ready" } })).toBe(
      false,
    );
    expect(viewsNeedAttention({ head_version_id: "ver_1", views: { state: "failed" } })).toBe(
      true,
    );
  });

  it("names an all-clear grant in one sentence and a broken one with a suffix", () => {
    expect(isAccessKey("all_clear")).toBe(true);
    expect(isAccessKey("All")).toBe(false);
    expect(ladderIssueKey("duplicate")).toBe("entities.access.ladders.invalid.duplicate");
    expect(levelOptionLabel("Clear", "clear")).toBe("Clear");
    expect(levelOptionLabel("Partial", "last4")).toBe("Partial (last4)");
    expect(profileIsAllClear([{ attribute_id: "att_name", level: "clear" }], ["att_name"])).toBe(
      true,
    );
    expect(profileIsAllClear([{ attribute_id: "att_name", level: "last4" }], ["att_name"])).toBe(
      false,
    );
    const labels: Record<string, string> = {
      "entities.access.summary.allClear": "All columns in full",
      "entities.access.action.read": "Read",
      "entities.access.action.write": "Write",
      "entities.access.summary.actionJoin": ", ",
      "entities.access.grants.allRows": "All rows",
      "entities.access.broken": "Broken",
    };
    expect(
      formatGrantLine((key) => labels[key] ?? key, {
        subject: "Super Admin",
        profileName: "all clear",
        actions: ["read", "write"],
        broken: false,
        rowRule: null,
        columns: [{ attribute_id: "att_name", level: "clear" }],
        attributeIds: ["att_name"],
        attributeName: (id) => id,
        attributeType: () => null,
      }),
    ).toBe("Super Admin · All columns in full · Read, Write · All rows");
    expect(
      formatGrantLine((key) => labels[key] ?? key, {
        subject: "Ada",
        profileName: "Finance",
        actions: ["read"],
        broken: true,
        rowRule: { eq: { attr: "att_region", value: "EAST" } },
        columns: [{ attribute_id: "att_name", level: "last4" }],
        attributeIds: ["att_name"],
        attributeName: (id) => (id === "att_region" ? "region" : id),
        attributeType: () => null,
      }),
    ).toBe("Ada · Finance · Read · region entities.access.rule.op.eq EAST · Broken");
  });

  it("reads a stored flat rule and labels time comparisons", () => {
    expect(parseStoredRule(null)).toEqual({ kind: "all" });
    expect(parseStoredRule({ or: [] })).toEqual({ kind: "custom" });
    expect(
      parseStoredRule({
        and: [{ eq: { attr: "att_region", value: "EAST" } }],
      }),
    ).toEqual({
      kind: "leaves",
      leaves: [
        {
          op: "eq",
          attributeId: "att_region",
          operand: { kind: "value", value: "EAST" },
        },
      ],
    });
    expect(ruleOpLabelKey("lt", "date")).toBe("entities.access.rule.op.lt.time");
    expect(ruleOpLabelKey("eq", "date")).toBe("entities.access.rule.op.eq");
    expect(ruleOpLabelKey("lt", "string")).toBe("entities.access.rule.op.lt");
    expect(
      ruleLeafPhrase({ attribute: "region", operator: "equals", operand: "EAST" }),
    ).toBe("region equals EAST");
    expect(
      sameProfileColumns(
        ["att_name"],
        [{ attribute_id: "att_name", level: "clear" }],
        { att_name: "clear" },
      ),
    ).toBe(true);
    expect(
      sameProfileColumns(
        ["att_name"],
        [{ attribute_id: "att_name", level: "clear" }],
        { att_name: "last4" },
      ),
    ).toBe(false);
    expect(
      levelReferrers(
        [
          {
            name: "Finance",
            columns: [{ attribute_id: "att_name", level: "last4" }],
          },
        ],
        [{ ceilings: [{ attribute_id: "att_name", level: "last4" }] }],
        "att_name",
        "last4",
      ),
    ).toEqual({ profileNames: ["Finance"], restrictionCount: 1 });
  });
});

describe("access orientation", () => {
  const clear = [{ levels: [{ key: "clear" }] }];
  const vague = [{ levels: [{ key: "clear" }, { key: "last4" }] }];

  it("emphasizes the first unfinished step and leaves the override unemphasized", () => {
    expect(accessChainSteps({ ladderCount: 0, profileCount: 0, grantCount: 0 })).toEqual([
      { id: "ladders", emphasis: true },
      { id: "profiles", emphasis: false },
      { id: "grants", emphasis: false },
      { id: "restrictions", emphasis: false },
    ]);
    expect(accessChainSteps({ ladderCount: 2, profileCount: 0, grantCount: 0 })[1]).toEqual({
      id: "profiles",
      emphasis: true,
    });
    expect(accessChainSteps({ ladderCount: 2, profileCount: 1, grantCount: 0 })[2]).toEqual({
      id: "grants",
      emphasis: true,
    });
    expect(
      accessChainSteps({ ladderCount: 2, profileCount: 1, grantCount: 1 }).some(
        (step) => step.emphasis,
      ),
    ).toBe(false);
  });

  it("counts grants per scheme", () => {
    expect(profileGrantCount("pro_all", [{ profile_id: "pro_all" }, { profile_id: "pro_all" }])).toBe(
      2,
    );
    expect(profileGrantCount("pro_new", [{ profile_id: "pro_all" }])).toBe(0);
  });

  it("picks one next step from the current summary", () => {
    expect(
      accessGuide({ ladders: [], profiles: [], grants: [], restrictionCount: 0 }),
    ).toEqual({ kind: "no_attributes" });
    expect(
      accessGuide({
        ladders: clear,
        profiles: [{ id: "pro_all", name: "All clear" }],
        grants: [{ profile_id: "pro_all" }],
        restrictionCount: 0,
      }),
    ).toEqual({ kind: "seed_only" });
    expect(
      accessGuide({
        ladders: clear,
        profiles: [{ id: "pro_all", name: "All clear" }],
        grants: [],
        restrictionCount: 0,
      }),
    ).toEqual({ kind: "unused_profiles", names: ["All clear"] });
    expect(
      accessGuide({
        ladders: clear,
        profiles: [
          { id: "pro_all", name: "All clear" },
          { id: "pro_narrow", name: "Narrow" },
        ],
        grants: [{ profile_id: "pro_all" }],
        restrictionCount: 0,
      }),
    ).toEqual({ kind: "none" });
    expect(
      accessGuide({
        ladders: vague,
        profiles: [{ id: "pro_all", name: "All clear" }],
        grants: [{ profile_id: "pro_all" }],
        restrictionCount: 0,
      }),
    ).toEqual({ kind: "none" });
    expect(
      accessGuide({
        ladders: clear,
        profiles: [{ id: "pro_all", name: "All clear" }],
        grants: [{ profile_id: "pro_all" }],
        restrictionCount: 1,
      }),
    ).toEqual({ kind: "none" });
    expect(laddersClearOnly(clear)).toBe(true);
    expect(laddersClearOnly(vague)).toBe(false);
    expect(laddersClearOnly([])).toBe(false);
  });

  it("derives a key from a name and leaves a name with no letters blank", () => {
    expect(accessKeyFromName("All clear")).toBe("all_clear");
    expect(accessKeyFromName("1 region")).toBe("p_1_region");
    expect(accessKeyFromName("财务")).toBe("");
    expect(accessKeyFromName("   ")).toBe("");
  });
});
