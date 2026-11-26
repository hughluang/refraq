import { describe, expect, it } from "vitest";

import { RouteIcon, SubchannelIcon, UndoIcon } from "@/components/icons";
import { extractSubchannelParams, subchannelParamSchema } from "@/features/channels/CallChannelFields";
import { fieldsFromSchema } from "@/features/channels/configSchemaForm";
import {
  localSubchannelOutputSchema,
  localSubchannelProblems,
} from "@/features/channels/graphValidation";
import { nodeTypeIcon } from "@/features/channels/nodeVisual";
import { returnNodeOffered } from "@/features/channels/paletteOffer";
import { formatJobTrigger } from "@/features/jobs/formatJobTrigger";
import en from "@/locales/en-US/common.json";
import zh from "@/locales/zh-CN/common.json";

describe("sub-channel palette and visual helpers", () => {
  it("offers action.return only when the graph trigger is trigger.subchannel", () => {
    expect(returnNodeOffered([])).toBe(false);
    expect(
      returnNodeOffered([{ type: "trigger.manual", trigger: true, config: {} }]),
    ).toBe(false);
    expect(
      returnNodeOffered([
        {
          type: "trigger.inbound",
          trigger: true,
          config: { response: { mode: "respond_node" } },
        },
      ]),
    ).toBe(false);
    expect(
      returnNodeOffered([{ type: "trigger.subchannel", trigger: true, config: { input: [] } }]),
    ).toBe(true);
  });

  it("maps sub-channel node icons and job trigger label", () => {
    expect(nodeTypeIcon("trigger.subchannel", "trigger")).toBe(SubchannelIcon);
    expect(nodeTypeIcon("action.return", "action")).toBe(UndoIcon);
    expect(nodeTypeIcon("action.call_channel", "action")).toBe(RouteIcon);
    expect(formatJobTrigger({ trigger_kind: "subchannel" }, (key) => key)).toBe(
      "jobs.trigger.subchannel",
    );
  });
});

describe("CallChannelFields contract extraction", () => {
  it("extracts typed parameters and dataset schemas from a published sub-channel graph", () => {
    const params = extractSubchannelParams({
      nodes: [
        {
          id: "nd_trig",
          type: "trigger.subchannel",
          config: {
            input: [
              { name: "entity_id", type: "string", required: true, description: "Target entity" },
              { name: "batch_limit", type: "integer", required: false, default: 500 },
              { name: "rows_ds", type: "dataset", required: true },
            ],
          },
        },
      ],
    });
    expect(params).toEqual([
      {
        name: "entity_id",
        type: "string",
        required: true,
        hasDefault: false,
        defaultValue: undefined,
        description: "Target entity",
      },
      {
        name: "batch_limit",
        type: "integer",
        required: false,
        hasDefault: true,
        defaultValue: 500,
        description: "",
      },
      {
        name: "rows_ds",
        type: "dataset",
        required: true,
        hasDefault: false,
        defaultValue: undefined,
        description: "",
      },
    ]);

    expect(subchannelParamSchema(params![0]!)).toEqual({ type: "string" });
    expect(subchannelParamSchema(params![1]!)).toEqual({ type: "integer" });
    expect(subchannelParamSchema(params![2]!)).toMatchObject({
      type: "object",
      required: ["dataset_id", "columns", "count"],
    });
  });

  it("returns null when graph trigger is not trigger.subchannel", () => {
    expect(
      extractSubchannelParams({
        nodes: [{ id: "nd_trig", type: "trigger.manual", config: {} }],
      }),
    ).toBeNull();
  });
});

describe("execution-resolved entity field schema", () => {
  it("marks entity fields with x-refraq-resolve=execution", () => {
    const fields = fieldsFromSchema({
      type: "object",
      required: ["entity_id", "target_id"],
      properties: {
        entity_id: {
          type: "string",
          "x-refraq-ref": "entity",
          "x-refraq-resolve": "execution",
        },
        target_id: {
          type: "string",
          "x-refraq-ref": "entity",
        },
      },
    });
    expect(fields).toEqual([
      {
        kind: "entity",
        key: "entity_id",
        required: true,
        description: "",
        executionResolved: true,
      },
      {
        kind: "entity",
        key: "target_id",
        required: true,
        description: "",
        executionResolved: false,
      },
    ]);
  });
});

describe("sub-channel locale parity", () => {
  it("keeps all sub-channel UI and problem keys present in both en-US and zh-CN", () => {
    const enMap = en as Record<string, string>;
    const zhMap = zh as Record<string, string>;
    const keys = [
      "jobs.trigger.subchannel",
      "channels.runs.trigger.subchannel",
      "channels.runDetail.calledBy",
      "channels.runDetail.openSubchannelRun",
      "channelNodeTypes.trigger.subchannel.label",
      "channelNodeTypes.trigger.subchannel.summary",
      "channelNodeTypes.action.return.label",
      "channelNodeTypes.action.return.summary",
      "channelNodeTypes.action.call_channel.label",
      "channelNodeTypes.action.call_channel.summary",
      "problems.CHANNEL_IN_USE",
      "problems.CHANNEL_SUBCHANNEL_TRIGGER_REQUIRED",
      "problems.CHANNEL_SUBCHANNEL_CYCLE",
      "problems.CHANNEL_SUBCHANNEL_INACTIVE",
      "problems.CHANNEL_SUBCHANNEL_UNAVAILABLE",
      "problems.CHANNEL_SUBCHANNEL_INPUT_INVALID",
      "problems.CHANNEL_SUBCHANNEL_DEPTH_EXCEEDED",
      "problems.CHANNEL_SUBCHANNEL_FAILED",
      "channels.config.entityMode.picker",
      "channels.config.entityMode.template",
    ];
    for (const key of keys) {
      expect(enMap[key], `missing en-US key ${key}`).toBeTruthy();
      expect(zhMap[key], `missing zh-CN key ${key}`).toBeTruthy();
    }
  });
});

describe("client-side subchannel output refinement and validation", () => {
  it("refines trigger.subchannel and action.call_channel output schemas locally", () => {
    const trigSchema = localSubchannelOutputSchema("trigger.subchannel", {
      input: [
        { name: "_cursor", type: "integer", required: true },
        { name: "from", type: "string", required: false, default: "erp" },
        { name: "note", type: "string", required: false },
      ],
    });
    expect(trigSchema).toEqual({
      type: "object",
      additionalProperties: false,
      required: ["_cursor", "from"],
      properties: {
        _cursor: { type: "integer" },
        from: { type: "string" },
        note: { type: ["string", "null"] },
      },
    });

    const callSchema = localSubchannelOutputSchema("action.call_channel", {});
    expect(callSchema?.required).toEqual([
      "job_id",
      "channel_id",
      "version",
      "outcome",
      "result",
    ]);
  });

  it("flags action.return without trigger.subchannel, default/sample_input mismatches, and self-calls immediately", () => {
    const problems = localSubchannelProblems(
      [
        { id: "nd_t", type: "trigger.manual", config: {} },
        { id: "nd_r", type: "action.return", config: { value: "1" } },
        { id: "nd_c", type: "action.call_channel", config: { channel_id: "" } },
        { id: "nd_self", type: "action.call_channel", config: { channel_id: "chn_me" } },
      ],
      "chn_me",
    );
    expect(problems.map((p) => [p.node_id, p.code, p.path])).toEqual([
      ["nd_r", "CHANNEL_NODE_CONFIG_INVALID", []],
      ["nd_c", "CHANNEL_NODE_CONFIG_INVALID", ["channel_id"]],
      ["nd_self", "CHANNEL_REFERENCE_UNRESOLVED", ["channel_id"]],
    ]);

    const triggerProblems = localSubchannelProblems([
      {
        id: "nd_sub",
        type: "trigger.subchannel",
        config: {
          input: [
            { name: "cnt", type: "integer", required: true },
            { name: "env", type: "string", required: false, default: 123 },
          ],
          sample_input: { cnt: null, env: "ok", extra: 1 },
        },
      },
    ]);
    expect(triggerProblems.map((p) => [p.code, p.path])).toEqual([
      ["CHANNEL_NODE_CONFIG_INVALID", ["input", 1, "default"]],
      ["CHANNEL_NODE_CONFIG_INVALID", ["sample_input", "cnt"]],
      ["CHANNEL_NODE_CONFIG_INVALID", ["sample_input", "extra"]],
    ]);
  });
});
