import { describe, expect, it } from "vitest";

import type { SchemaObject } from "@/features/channels/configSchemaForm";
import { child, children, parseAccess } from "@/features/channels/templateScope";

const CLOSED: SchemaObject = {
  type: "object",
  additionalProperties: false,
  properties: {
    rows: { type: "array" },
    triggered_by: {
      type: "object",
      additionalProperties: false,
      properties: { id: { type: "string" }, name: { type: "string" } },
    },
  },
};

describe("children", () => {
  it("keeps a closed object on its declared keys", () => {
    expect(children(CLOSED, { rows: [], extra: 1, triggered_by: { id: "u" } })).toEqual([
      "rows",
      "triggered_by",
    ]);
  });

  it("merges identifier sample keys when additional properties are open", () => {
    expect(children({ type: "object", properties: { rows: {} } }, { rows: [], extra: 1 })).toEqual([
      "rows",
      "extra",
    ]);
    expect(children(null, { rows: [], "not ident": 1 })).toEqual(["rows"]);
    expect(children({ type: "array" }, ["rows"])).toEqual([]);
  });
});

describe("child", () => {
  it("walks a declared nested object and refuses a key a closed schema does not have", () => {
    const nested = child(CLOSED, { triggered_by: { id: "u", name: "root" } }, "triggered_by");
    expect(nested?.schema?.properties).toHaveProperty("id");
    expect(child(nested?.schema, nested?.sample, "id")?.schema).toEqual({ type: "string" });
    expect(child(CLOSED, { extra: { id: "u" } }, "extra")).toBeNull();
  });
});

describe("parseAccess", () => {
  it("reads a partial attribute, a bracket key, and ignores a chain that does not reach the cursor", () => {
    const dotted = "{{ self.run_manually.";
    expect(parseAccess(dotted, dotted.length)).toEqual({
      start: 3,
      segments: [{ kind: "attr", name: "run_manually" }],
      filter: "",
    });
    const named = '{{ self.nodes["Run"].output.tri';
    expect(parseAccess(named, named.length)).toEqual({
      start: 3,
      segments: [
        { kind: "attr", name: "nodes" },
        { kind: "key", name: "Run" },
        { kind: "attr", name: "output" },
      ],
      filter: "tri",
    });
    expect(parseAccess("self.", 5)).toEqual({
      start: 0,
      segments: [],
      filter: "",
    });
    const closed = '{{ self.nodes["Run"]';
    expect(parseAccess(closed, closed.length)).toBeNull();
  });
});
