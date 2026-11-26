import { describe, expect, it } from "vitest";

import type { AccessLadder, AccessSummary } from "@/features/entities/accessTypes";
import {
  availableOperandKinds,
  formatMaskSample,
  manualLiveSchedule,
  memoryAccessPort,
  openAccessWorkbench,
  parseRuleTree,
  ruleTreeMetrics,
  serializeRuleTree,
  summarizeRuleCompact,
  type RuleTreeNode,
} from "@/features/entities/accessWorkbench";

function makeSummary(overrides: Partial<AccessSummary> = {}): AccessSummary {
  return {
    entity_id: "ent_1",
    head_version_id: "ver_1",
    policy_revision: 1,
    views: {
      state: "ready",
      revision: 1,
      single_profile_views: 1,
      combinations: 1,
      combination_limit: 64,
      subjects_over_limit: 0,
      latest_job_id: null,
    },
    ladders: [
      {
        attribute_id: "att_email",
        attribute_name: "email",
        attribute_display_name: "Email",
        type: "string",
        value_type: "string",
        accepted_masks: ["clear", "partial", "email", "hash", "redact", "null"],
        operators: ["eq", "neq", "in", "not_in", "contains", "starts_with", "is_null", "is_not_null"],
        compatible_subject_attributes: [{ key: "team", name: "Team", value_type: "string", multi_value: false }],
        levels: [
          { key: "clear", mode: "clear" },
          { key: "masked", mode: { type: "email" } },
          { key: "hidden", mode: { type: "redact" } },
        ],
      },
      {
        attribute_id: "att_age",
        attribute_name: "age",
        attribute_display_name: "Age",
        type: "integer",
        value_type: "integer",
        accepted_masks: ["clear", "bucket", "redact", "null"],
        operators: ["eq", "neq", "gt", "gte", "lt", "lte", "in", "not_in", "is_null", "is_not_null"],
        compatible_subject_attributes: [],
        levels: [
          { key: "clear", mode: "clear" },
          { key: "decade", mode: { type: "bucket", width: 10 } },
        ],
      },
    ],
    profiles: [
      {
        id: "prf_1",
        entity_id: "ent_1",
        key: "analyst",
        name: "Analyst",
        description: null,
        columns: [
          { attribute_id: "att_email", attribute_name: "email", level: "masked" },
          { attribute_id: "att_age", attribute_name: "age", level: "clear" },
        ],
        broken: false,
        broken_reasons: [],
      },
    ],
    grants: [
      {
        id: "grt_1",
        subject: { type: "user", id: "usr_ada", display_name: "Ada" },
        profile_id: "prf_1",
        row_rule: {
          and: [
            { gte: { attr: "att_age", value: 18 } },
            { not: { eq: { attr: "att_email", value: "blocked@example.com" } } },
          ],
        },
        actions: ["read"],
        status: "active",
        valid_until: null,
        locked: false,
        broken: false,
        broken_reasons: [],
        warnings: [],
      },
    ],
    restrictions: [],
    ...overrides,
  };
}

describe("accessWorkbench rule codec & mask samples", () => {
  it("round-trips nested AND/OR/NOT trees and computes leaf/depth metrics", () => {
    const raw = {
      and: [
        { gte: { attr: "att_age", value: 21 } },
        {
          or: [
            { contains: { attr: "att_email", value: "@acme.io" } },
            { not: { eq: { attr: "att_email", subject_attr: "team" } } },
          ],
        },
      ],
    };
    const parsed = parseRuleTree(raw);
    expect(parsed).not.toBeNull();
    const metrics = ruleTreeMetrics(parsed as RuleTreeNode);
    expect(metrics.leaves).toBe(3);
    expect(metrics.depth).toBe(4);
    expect(serializeRuleTree(parsed!)).toEqual(raw);
    expect(summarizeRuleCompact(parsed!, (k) => k, (id) => id, () => "string")).toContain("@acme.io");
  });

  it("derives available operand kinds from server-projected ladder capabilities", () => {
    const ladders = makeSummary().ladders;
    expect(availableOperandKinds(ladders[0], "eq")).toEqual(["value"]);
    expect(availableOperandKinds(ladders[0], "in")).toEqual(["value", "subject_attr"]);
    expect(availableOperandKinds(ladders[1], "gte")).toEqual(["value"]);
    const dateLadder: AccessLadder = {
      attribute_id: "att_dt",
      attribute_name: "created_at",
      attribute_display_name: "Created",
      type: "date",
      value_type: "date",
      operators: ["eq", "gte", "lte"],
      compatible_subject_attributes: [],
      levels: [{ key: "clear", mode: "clear" }],
    };
    expect(availableOperandKinds(dateLadder, "gte")).toEqual(["value", "rel_time"]);
  });

  it("formats deterministic mask samples for every mask mode", () => {
    const emailLadder = makeSummary().ladders[0];
    const ageLadder = makeSummary().ladders[1];
    expect(formatMaskSample(emailLadder, "clear")).toBe("ada@refraq.io");
    expect(formatMaskSample(emailLadder, { type: "email" })).toBe("a***@refraq.io");
    expect(
      formatMaskSample(emailLadder, { type: "partial", keep_first: 2, keep_last: 3 }, "13800138000"),
    ).toBe("13******000");
    expect(formatMaskSample(ageLadder, { type: "bucket", width: 10 }, "27")).toBe("20");
    expect(formatMaskSample(emailLadder, { type: "redact" })).toBe("[redacted]");
    expect(formatMaskSample(emailLadder, { type: "null" })).toBe("NULL");
  });
});

describe("openAccessWorkbench session", () => {
  it("mutates profile cells and toggles grant status via AccessPort", async () => {
    const port = memoryAccessPort(makeSummary());
    const schedule = manualLiveSchedule();
    const session = openAccessWorkbench({ entityId: "ent_1", canPreviewRows: true, port, schedule });

    await session.dispatch({ kind: "reload" });
    expect(session.snapshot().summary?.profiles[0].columns[0].level).toBe("masked");

    await session.dispatch({
      kind: "set_profile_cell",
      profileId: "prf_1",
      attributeId: "att_email",
      level: "clear",
    });
    expect(session.snapshot().summary?.profiles[0].columns[0].level).toBe("clear");

    const grant = session.snapshot().summary!.grants[0];
    await session.dispatch({ kind: "toggle_grant_status", grant });
    expect(session.snapshot().summary?.grants[0].status).toBe("disabled");
    session.dispose();
  });

  it("polls while views.state is pending and stops when ready", async () => {
    let polls = 0;
    const base = makeSummary({
      views: {
        state: "pending",
        revision: 1,
        single_profile_views: 1,
        combinations: 1,
        combination_limit: 64,
        subjects_over_limit: 0,
        latest_job_id: "job_9",
      },
    });
    const port = memoryAccessPort(base);
    const origLoad = port.loadSummary;
    port.loadSummary = async (entityId) => {
      polls += 1;
      const res = await origLoad(entityId);
      if (polls >= 3) {
        return { ...res, views: { ...res.views, state: "ready" } };
      }
      return res;
    };

    const schedule = manualLiveSchedule();
    const session = openAccessWorkbench({ entityId: "ent_1", canPreviewRows: false, port, schedule });
    await session.dispatch({ kind: "reload" });
    expect(session.snapshot().summary?.views.state).toBe("pending");

    await schedule.tick();
    expect(session.snapshot().summary?.views.state).toBe("ready");
    expect(polls).toBe(3);
    session.dispose();
  });

  it("pins a user, narrows identities, and tracks cell __sources hover attribution", async () => {
    const port = memoryAccessPort(makeSummary(), {
      policy_revision: 1,
      effective_grants: [],
      schema: {
        entity: { table_name: "entity", writable: false, name: "Entity" },
        attributes: [{ name: "email", level: "masked", value_type: "string" }],
        withheld_field: null,
        business_key: null,
      },
      rows: {
        items: [{ row_id: 1, email: "a***@example.com", __sources: { email: ["grt_1"] } }],
        total: 1,
      },
      identities: [
        { type: "user", id: null, display_name: "Ada" },
        { type: "role", id: "role_op", display_name: "Operator" },
        { type: "group", id: "grp_1", display_name: "Analytics" },
      ],
    });
    const session = openAccessWorkbench({
      entityId: "ent_1",
      canPreviewRows: true,
      port,
      schedule: manualLiveSchedule(),
    });

    await session.dispatch({ kind: "reload" });
    await session.dispatch({
      kind: "pin_user",
      userId: "usr_ada",
      displayName: "Ada",
      includeRows: true,
    });
    expect(session.snapshot().pin.kind).toBe("user");
    expect(session.snapshot().preview?.identities).toHaveLength(3);

    await session.dispatch({ kind: "set_narrow", narrow: { kind: "role", id: "role_op" } });
    expect(session.snapshot().pin).toMatchObject({
      kind: "user",
      narrow: { kind: "role", id: "role_op" },
    });

    await session.dispatch({
      kind: "hover",
      hover: { kind: "cell", rowIndex: 0, attributeName: "email", sources: ["grt_1"], withheld: false },
    });
    expect(session.snapshot().hover).toMatchObject({ kind: "cell", sources: ["grt_1"] });
    session.dispose();
  });
});
