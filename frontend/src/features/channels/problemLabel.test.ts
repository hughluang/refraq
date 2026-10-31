import { describe, expect, it } from "vitest";

import en from "@/locales/en-US/common.json";
import zh from "@/locales/zh-CN/common.json";
import {
  fieldMessages,
  formatGraphProblem,
  formatRunError,
  problemIdentity,
  type ProblemGraph,
} from "@/features/channels/problemLabel";
import type { GraphProblem } from "@/features/channels/types";

const t = (key: string, options?: Record<string, unknown>) => {
  if (key === "problems.CHANNEL_NODE_CONFIG_INVALID") return "Invalid node configuration";
  if (key === "problems.CHANNEL_TEMPLATE_TYPE_UNKNOWN") return "Checked at run time";
  if (key === "channels.canvas.problemEdge") return `${options?.source} → ${options?.target}`;
  return key;
};

const graph: ProblemGraph = {
  nodes: [
    { id: "nd_read", name: "Read suppliers" },
    { id: "nd_write", name: "Write orders" },
  ],
  edges: [
    {
      id: "ed_1",
      source: { node_id: "nd_read" },
      target: { node_id: "nd_write" },
    },
  ],
};

function problem(path: (string | number)[], detail: string): GraphProblem {
  return {
    code: "CHANNEL_NODE_CONFIG_INVALID",
    node_id: "nd_read",
    edge_id: null,
    path,
    detail,
  };
}

describe("formatGraphProblem", () => {
  it("keeps a translated problem without a path as the translation", () => {
    expect(
      formatGraphProblem(
        t,
        {
          code: "CHANNEL_NODE_CONFIG_INVALID",
          node_id: "nd_read",
          edge_id: null,
          path: [],
          detail: "Mapping names an attribute more than once",
        },
        graph,
      ),
    ).toBe("Invalid node configuration (Read suppliers)");
  });

  it("adds the property path and constraint when a path is present", () => {
    expect(
      formatGraphProblem(t, problem(["statement_timeout_sec"], "None is not of type 'integer'"), graph),
    ).toBe(
      "Invalid node configuration: statement_timeout_sec — None is not of type 'integer' (Read suppliers)",
    );
  });

  it("writes a catalog bound with the field's interface name", () => {
    const translate = (key: string, options?: Record<string, unknown>) => {
      const table: Record<string, string> = {
        "problems.CHANNEL_NODE_CONFIG_INVALID": "Invalid node configuration",
        "channels.config.fields.volume.until.max_iterations": "Max rounds",
        "channels.config.fields.volume.until.until": "Until",
        "channels.config.constraint.required": "{{name}} is required.",
        "channels.config.constraint.minimum": "{{name}} is below the minimum of {{bound}}.",
        "channels.config.constraint.maximum": "{{name}} is above the maximum of {{bound}}.",
        "channels.config.constraint.minLength": "{{name}} is shorter than the minimum length of {{bound}}.",
      };
      const raw = table[key] ?? key;
      if (!options) return raw;
      return raw.replace(/\{\{(\w+)\}\}/g, (_, name: string) => String(options[name] ?? ""));
    };
    const withSchema: ProblemGraph = {
      nodes: [{ id: "nd_read", name: "Read suppliers", type: "volume.until" }],
      edges: [],
      configSchemas: {
        "volume.until": {
          type: "object",
          required: ["max_iterations", "until"],
          properties: {
            max_iterations: { type: "integer", minimum: 1, maximum: 100000 },
            until: { type: "string", minLength: 1 },
          },
        },
      },
    };
    expect(
      formatGraphProblem(
        translate,
        problem(["max_iterations"], "0 is less than the minimum of 1"),
        withSchema,
      ),
    ).toBe("Invalid node configuration: Max rounds is below the minimum of 1. (Read suppliers)");
    expect(
      formatGraphProblem(
        translate,
        problem(["max_iterations"], "100001 is greater than the maximum of 100000"),
        withSchema,
      ),
    ).toBe("Invalid node configuration: Max rounds is above the maximum of 100000. (Read suppliers)");
    expect(
      formatGraphProblem(
        translate,
        problem(["until"], "'until' is a required property"),
        withSchema,
      ),
    ).toBe("Invalid node configuration: Until is required. (Read suppliers)");
    expect(
      formatGraphProblem(translate, problem(["until"], "'' should be non-empty"), withSchema),
    ).toBe(
      "Invalid node configuration: Until is shorter than the minimum length of 1. (Read suppliers)",
    );
    expect(
      formatGraphProblem(
        translate,
        problem(["max_iterations"], "None is not of type 'integer'"),
        withSchema,
      ),
    ).toBe(
      "Invalid node configuration: max_iterations — None is not of type 'integer' (Read suppliers)",
    );
  });

  it("omits a contract sentence that repeats the localized line", () => {
    const messages = zh as Record<string, string>;
    const english = en as Record<string, string>;
    const translate = catalogTranslate(messages);
    const cases = [
      ["CHANNEL_TEMPLATE_TYPE_MISMATCH", "until"],
      ["CHANNEL_TEMPLATE_TYPE_UNKNOWN", "fields.0.value"],
      ["CHANNEL_EXPRESSION_INVALID", "name"],
    ] as const;
    for (const [code, path] of cases) {
      expect(
        formatGraphProblem(
          translate,
          {
            code,
            node_id: "nd_read",
            edge_id: null,
            path: path.split("."),
            detail: english[`problems.${code}`],
          },
          graph,
        ),
      ).toBe(`${messages[`problems.${code}`]}: ${path} (Read suppliers)`);
    }
  });

  it("omits the node name when the panel already shows that node", () => {
    expect(
      formatGraphProblem(t, problem([], "Mapping names an attribute more than once"), graph, {
        nodeName: false,
      }),
    ).toBe("Invalid node configuration");
  });

  it("names an edge by the display names of its ends", () => {
    expect(
      formatGraphProblem(
        t,
        {
          code: "CHANNEL_PORT_TYPE_MISMATCH",
          node_id: "nd_write",
          edge_id: "ed_1",
          path: [],
          detail: "Ports have incompatible types",
        },
        graph,
        { nodeName: false },
      ),
    ).toBe("Ports have incompatible types (Read suppliers → Write orders)");
  });

  it("names the one end that resolves and omits a missing edge", () => {
    expect(
      formatGraphProblem(
        t,
        {
          code: "CHANNEL_GRAPH_EDGE_INVALID",
          node_id: "nd_missing",
          edge_id: "ed_1",
          path: [],
          detail: "Edge names an unknown node or port",
        },
        {
          nodes: [{ id: "nd_read", name: "Read suppliers" }],
          edges: [
            {
              id: "ed_1",
              source: { node_id: "nd_read" },
              target: { node_id: "nd_missing" },
            },
          ],
        },
      ),
    ).toBe("Edge names an unknown node or port (Read suppliers)");
    expect(
      formatGraphProblem(
        t,
        {
          code: "CHANNEL_GRAPH_EDGE_INVALID",
          node_id: "nd_read",
          edge_id: "ed_gone",
          path: [],
          detail: "Edge names an unknown node or port",
        },
        graph,
      ),
    ).toBe("Edge names an unknown node or port");
  });
});

describe("fieldMessages", () => {
  it("uses the problem-list sentence and keeps severity", () => {
    const problems = [
      problem(["statement_timeout_sec"], "None is not of type 'integer'"),
      problem(["mapping", 0, "attribute"], "'attribute' is a required property"),
      {
        code: "CHANNEL_TEMPLATE_TYPE_UNKNOWN",
        node_id: "nd_read",
        edge_id: null,
        path: ["value"],
        detail: (en as Record<string, string>)["problems.CHANNEL_TEMPLATE_TYPE_UNKNOWN"],
        severity: "warning" as const,
      },
    ];
    expect(fieldMessages(t, problems, "statement_timeout_sec", graph)).toEqual([
      {
        text: "Invalid node configuration: statement_timeout_sec — None is not of type 'integer'",
        severity: "error",
      },
    ]);
    expect(fieldMessages(t, problems, "mapping", graph)).toEqual([
      {
        text: "Invalid node configuration: mapping.0.attribute — 'attribute' is a required property",
        severity: "error",
      },
    ]);
    expect(fieldMessages(t, problems, "value", graph)).toEqual([
      {
        text: "Checked at run time: value",
        severity: "warning",
      },
    ]);
    expect(fieldMessages(t, problems, "sql", graph)).toEqual([]);
  });
});

describe("problemIdentity", () => {
  it("keeps two configuration failures on one node distinct", () => {
    const left = problemIdentity(problem(["sql"], "'' is too short"));
    const right = problemIdentity(
      problem(["statement_timeout_sec"], "None is not of type 'integer'"),
    );
    expect(left).not.toBe(right);
  });
});

const LOOP_BODY_REASONS = [
  ["parent does not name a container", "problems.CHANNEL_LOOP_BODY_INVALID.parent"],
  ["parent chain contains a cycle", "problems.CHANNEL_LOOP_BODY_INVALID.cycle"],
  ["Edge crosses a container frame", "problems.CHANNEL_LOOP_BODY_INVALID.cross"],
  ["A container frame is entered only from each", "problems.CHANNEL_LOOP_BODY_INVALID.entry"],
  [
    "each connects only to a direct child of this container",
    "problems.CHANNEL_LOOP_BODY_INVALID.each",
  ],
] as const;

function catalogTranslate(catalog: Record<string, string>) {
  return (key: string, options?: Record<string, unknown>) => {
    const raw = catalog[key];
    if (raw == null) return key;
    if (!options) return raw;
    return raw.replace(/\{\{(\w+)\}\}/g, (_, name: string) => String(options[name] ?? ""));
  };
}

function loopBody(detail: string, edgeId: string | null = null): GraphProblem {
  return {
    code: "CHANNEL_LOOP_BODY_INVALID",
    node_id: "nd_read",
    edge_id: edgeId,
    path: [],
    detail,
  };
}

describe("frame-rule sentences", () => {
  it.each([
    ["zh-CN", zh],
    ["en-US", en],
  ] as const)("%s names each frame reason and keeps the node", (locale, catalog) => {
    const messages = catalog as Record<string, string>;
    const translate = catalogTranslate(messages);
    const fallback = messages["problems.CHANNEL_LOOP_BODY_INVALID"];
    expect(fallback).not.toContain("For");
    expect(fallback).not.toBe("");

    for (const [detail, key] of LOOP_BODY_REASONS) {
      const sentence = messages[key];
      expect(sentence, `${locale} ${key}`).toBeTruthy();
      expect(formatGraphProblem(translate, loopBody(detail), graph)).toBe(
        `${sentence} (Read suppliers)`,
      );
    }

    expect(formatGraphProblem(translate, loopBody("a new frame rule"), graph)).toBe(
      `${fallback} (Read suppliers)`,
    );
  });

  it("uses the server message when an Until volume failure is not the For sentence", () => {
    const enMessages = en as Record<string, string>;
    const zhMessages = zh as Record<string, string>;
    const forSentence = "For iteration output exceeds 16 MiB. Read the items in batches.";
    const untilSentence = "Until iteration output exceeds 16 MiB.";
    expect(enMessages["problems.CHANNEL_ITERATION_VOLUME_EXCEEDED"]).toBe(forSentence);
    expect(formatRunError(catalogTranslate(zhMessages), "CHANNEL_ITERATION_VOLUME_EXCEEDED", forSentence)).toEqual({
      label: zhMessages["problems.CHANNEL_ITERATION_VOLUME_EXCEEDED"],
      detail: null,
    });
    expect(formatRunError(catalogTranslate(zhMessages), "CHANNEL_ITERATION_VOLUME_EXCEEDED", untilSentence)).toEqual({
      label: untilSentence,
      detail: untilSentence,
    });
    expect(zhMessages["problems.CHANNEL_UNTIL_MAX_ITERATIONS"]?.length).toBeGreaterThan(0);
    expect(zhMessages["problems.CHANNEL_UNTIL_MAX_ITERATIONS"]).not.toBe(
      enMessages["problems.CHANNEL_UNTIL_MAX_ITERATIONS"],
    );
    expect(
      formatRunError(
        catalogTranslate(enMessages),
        "CHANNEL_UNTIL_MAX_ITERATIONS",
        "Until reached max_iterations before its condition became true.",
      ).label,
    ).toBe("Until reached max_iterations before its condition became true.");
  });

  it("uses the locale sentence for a change-log contract message", () => {
    const enMessages = en as Record<string, string>;
    const zhMessages = zh as Record<string, string>;
    const cases = [
      ["CHANNEL_CHANGE_LOG_OFF", "Change recording is off for this entity."],
      ["CHANNEL_CHECKPOINT_INVALID", "Checkpoint is behind deleted change-log entries."],
    ] as const;
    for (const [code, message] of cases) {
      const key = `problems.${code}`;
      expect(enMessages[key]).toBe(message);
      expect(zhMessages[key]).toBeTruthy();
      expect(zhMessages[key]).not.toBe(message);
      expect(zhMessages[key]).not.toContain(code);
      expect(formatRunError(catalogTranslate(zhMessages), code, message)).toEqual({
        label: zhMessages[key],
        detail: null,
      });
      expect(formatRunError(catalogTranslate(enMessages), code, message)).toEqual({
        label: message,
        detail: null,
      });
      expect(formatRunError((key) => key, code, message)).toEqual({
        label: message,
        detail: null,
      });
    }
  });

  it("keeps an edge place on a frame reason and does not append the English detail", () => {
    const translate = catalogTranslate(zh as Record<string, string>);
    expect(
      formatGraphProblem(translate, loopBody("Edge crosses a container frame", "ed_1"), graph, {
        nodeName: false,
      }),
    ).toBe("\u8fde\u7ebf\u7a7f\u8fc7\u4e86\u6846 (Read suppliers → Write orders)");
  });
});
