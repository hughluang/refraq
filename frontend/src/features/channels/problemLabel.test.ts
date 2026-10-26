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
        detail: "Template result type is not known until the node runs",
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
        text: "Checked at run time: value — Template result type is not known until the node runs",
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
      detail: forSentence,
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

  it("keeps an edge place on a frame reason and does not append the English detail", () => {
    const translate = catalogTranslate(zh as Record<string, string>);
    expect(
      formatGraphProblem(translate, loopBody("Edge crosses a container frame", "ed_1"), graph, {
        nodeName: false,
      }),
    ).toBe("\u8fde\u7ebf\u7a7f\u8fc7\u4e86\u6846 (Read suppliers → Write orders)");
  });
});
