import { describe, expect, it } from "vitest";

import { filterNodeTypes, pickerOrigin } from "@/features/channels/nodePicker";

const specs = [
  { type: "read.sql", label: "SQL", summary: "Runs SQL" },
  { type: "transform.if", label: "If", summary: "True or false" },
];

describe("filterNodeTypes", () => {
  const identity = (key: string, options?: { defaultValue?: string }) =>
    options?.defaultValue ?? key;

  it("returns every spec, in order, when the query is blank", () => {
    expect(filterNodeTypes(specs, "   ", identity).map((item) => item.type)).toEqual([
      "read.sql",
      "transform.if",
    ]);
  });

  it("matches translated names and summaries without caring about case", () => {
    const t = (key: string, options?: { defaultValue?: string }) => {
      if (key === "channelNodeTypes.read.sql.label") return "Query";
      if (key === "channelNodeTypes.transform.if.summary") return "Branches";
      return options?.defaultValue ?? key;
    };
    expect(filterNodeTypes(specs, "  query ", t).map((item) => item.type)).toEqual(["read.sql"]);
    expect(filterNodeTypes(specs, "BRANCH", t).map((item) => item.type)).toEqual(["transform.if"]);
    expect(filterNodeTypes(specs, "nope", t)).toEqual([]);
  });
});

describe("pickerOrigin", () => {
  it("keeps a 320 by 420 box inside the stage, above the anchor when asked", () => {
    expect(pickerOrigin({ x: 20, y: 500 }, { width: 800, height: 600 }, true)).toEqual({
      left: 20,
      top: 500 - 420 - 8,
    });
    expect(pickerOrigin({ x: 900, y: 580 }, { width: 800, height: 600 }, false)).toEqual({
      left: 800 - 320 - 8,
      top: 600 - 420 - 8,
    });
    expect(pickerOrigin({ x: -10, y: -10 }, { width: 200, height: 100 }, false)).toEqual({
      left: 8,
      top: 8,
    });
  });
});