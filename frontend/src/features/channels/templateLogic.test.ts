import { describe, expect, it } from "vitest";

import type { SchemaObject } from "@/features/channels/configSchemaForm";
import {
  resolvedText,
  templateCompletions,
  templatePreview,
  templateRule,
  upstreamOutputs,
} from "@/features/channels/templateLogic";
import type { SelfScope } from "@/features/channels/templateScope";

const LIST = { type: "array", items: { type: "object" } } as const;

describe("templatePreview", () => {
  it("accepts static JSON for a list without braces", () => {
    expect(templatePreview('[{"sku": "BT-abc"}]', LIST).state).toBe("ok");
  });

  it("rejects static text that is not the declared type", () => {
    expect(templatePreview("not-json", LIST).state).toBe("error");
  });

  it("defers a whole expression and keeps a string concatenation typed", () => {
    expect(templatePreview('{{ "def" }}', { type: "string" }).state).toBe("deferred");
    expect(templatePreview('abc{{ "def" }}', { type: "string" }).state).toBe("string");
    expect(templatePreview('[{"sku": "{{ 1 }}"}]', LIST).state).toBe("deferred");
  });

  it("treats an escaped brace as static text", () => {
    expect(templatePreview("\\{{ not code }}", { type: "string" })).toEqual({
      state: "ok",
      value: "{{ not code }}",
    });
  });

  it("marks an unclosed expression before a schema is known", () => {
    expect(templatePreview("{{ self.read", { type: "string" }).state).toBe("invalid");
    expect(templatePreview("{{  }}", null).state).toBe("invalid");
    expect(templatePreview("hello", null).state).toBe("unknown");
  });

  it("keeps quoted text as the string value", () => {
    const preview = templatePreview('"BT-abc"', { type: "string" });
    expect(preview).toEqual({ state: "ok", value: '"BT-abc"' });
    expect(resolvedText('"BT-abc"')).toBe('"\\"BT-abc\\""');
  });

  it("rejects a quoted integer and accepts a bare integer", () => {
    expect(templatePreview('"8"', { type: "integer" }).state).toBe("error");
    expect(templatePreview("8", { type: "integer" })).toEqual({ state: "ok", value: 8 });
  });

  it("names the reading rule from the declared type", () => {
    expect(templateRule({ type: ["string", "null"] })).toBe("text");
    expect(templateRule({ type: "integer" })).toBe("json");
    expect(templateRule(null)).toBeNull();
  });

  it("shortens a long resolved value", () => {
    const shown = resolvedText("x".repeat(90));
    expect(shown).toHaveLength(80);
    expect(shown.endsWith("…")).toBe(true);
  });
});

const NO_CONTEXT = { channel: null, run: null, platform: null } as const;

function scopeOf(
  nodes: SelfScope["nodes"],
  context: SelfScope["context"] = NO_CONTEXT,
): SelfScope {
  return { nodes, context };
}

const READ_SCHEMA: SchemaObject = {
  type: "object",
  additionalProperties: false,
  properties: { rows: { type: "array" }, count: { type: "integer" } },
};

const MANUAL_SCHEMA: SchemaObject = {
  type: "object",
  additionalProperties: false,
  properties: {
    test: { type: "string" },
    triggered_at: { type: "string" },
    triggered_by: {
      type: "object",
      additionalProperties: false,
      properties: { id: { type: "string" }, name: { type: "string" } },
    },
  },
};

describe("completion", () => {
  const upstream = scopeOf([
    {
      ref: "read_entity",
      name: "Read entity",
      schema: READ_SCHEMA,
      sample: { rows: [], count: 0, extra: true },
    },
  ]);
  const roots = [
    "self.read_entity",
    "self.nodes",
    "self.channel",
    "self.run",
    "self.platform",
  ];

  it("suggests upstream refs and context names inside an expression", () => {
    const inside = templateCompletions("{{ self.", 8, false, upstream);
    expect(inside?.options).toEqual(roots);
    expect(templateCompletions("self.", 5, false, upstream)).toBeNull();
    expect(templateCompletions("{{ ", 3, true, upstream)?.options).toEqual(roots);
    expect(templateCompletions("{{ ", 3, false, upstream)).toBeNull();
    expect(templateCompletions('{{ "self.', 9, true, upstream)).toBeNull();
  });

  it("suggests upstream display names inside a node key", () => {
    const text = '{{ self.nodes["';
    expect(templateCompletions(text, text.length, false, upstream)).toEqual({
      from: 3,
      options: ['self.nodes["Read entity"]'],
    });
    const partial = '{{ self.nodes["Hold';
    expect(
      templateCompletions(
        partial,
        partial.length,
        true,
        scopeOf([
          ...upstream.nodes,
          { ref: "hold", name: "Hold", schema: null, sample: undefined },
        ]),
      )?.options,
    ).toEqual(['self.nodes["Hold"]']);
  });

  it("suggests the root on an explicit invoke inside empty braces", () => {
    const text = "{{  }}";
    const found = templateCompletions(text, 3, true, upstream);
    expect(found?.options).toEqual(roots);
    expect(templateCompletions(text, 3, false, upstream)).toBeNull();
  });

  it("suggests the next member of a closed schema and ignores sample keys", () => {
    const text = "{{ self.read_entity.output.";
    expect(templateCompletions(text, text.length, false, upstream)?.options).toEqual([
      "self.read_entity.output.rows",
      "self.read_entity.output.count",
    ]);
  });

  it("suggests output after a node ref and walks nested properties", () => {
    const manual = scopeOf([
      {
        ref: "run_manually",
        name: "Run",
        schema: MANUAL_SCHEMA,
        sample: { test: "2026-10-14T", surprise: 1, triggered_by: { id: "u", name: "root" } },
      },
    ]);
    const refDot = "{{ self.run_manually.";
    expect(templateCompletions(refDot, refDot.length, false, manual)?.options).toEqual([
      "self.run_manually.output",
    ]);
    const nested = "{{ self.run_manually.output.triggered_by.";
    expect(templateCompletions(nested, nested.length, false, manual)?.options).toEqual([
      "self.run_manually.output.triggered_by.id",
      "self.run_manually.output.triggered_by.name",
    ]);
    const named = '{{ self.nodes["Run"].output.';
    expect(templateCompletions(named, named.length, false, manual)?.options).toEqual([
      'self.nodes["Run"].output.test',
      'self.nodes["Run"].output.triggered_at',
      'self.nodes["Run"].output.triggered_by',
    ]);
  });

  it("merges sample keys when the schema does not close additional properties", () => {
    const open = scopeOf([
      {
        ref: "read_entity",
        name: "Read entity",
        schema: { type: "object", properties: { rows: { type: "array" } } },
        sample: { rows: [], extra: 1 },
      },
    ]);
    const text = "{{ self.read_entity.output.";
    expect(templateCompletions(text, text.length, false, open)?.options).toEqual([
      "self.read_entity.output.rows",
      "self.read_entity.output.extra",
    ]);
    const sampled = scopeOf([
      { ref: "read_entity", name: "Read entity", schema: null, sample: { rows: [] } },
    ]);
    expect(templateCompletions(text, text.length, false, sampled)?.options).toEqual([
      "self.read_entity.output.rows",
    ]);
  });

  it("suggests parameter keys from the platform schema", () => {
    const platform: SchemaObject = {
      type: "object",
      additionalProperties: false,
      properties: {
        parameters: {
          type: "object",
          additionalProperties: false,
          properties: {
            schedule_timezone: { type: "string" },
            keep_days: { type: "integer" },
          },
        },
      },
    };
    const text = "{{ self.platform.parameters.";
    expect(
      templateCompletions(text, text.length, false, scopeOf([], { ...NO_CONTEXT, platform }))
        ?.options,
    ).toEqual([
      "self.platform.parameters.schedule_timezone",
      "self.platform.parameters.keep_days",
    ]);
  });
});

describe("upstreamOutputs", () => {
  it("lists ancestors and not the node itself", () => {
    const found = upstreamOutputs(
      "write",
      [
        { id: "trigger", ref: "run_manually", name: "Run" },
        { id: "read", ref: "read_entity", name: "Read" },
        { id: "write", ref: "write_entity", name: "Write" },
      ],
      [
        { source: "trigger", target: "read" },
        { source: "read", target: "write" },
      ],
      new Map([["read", { type: "object", properties: { rows: {} } }]]),
      new Map([["trigger", { test: "x" }]]),
    );
    expect(found.map((item) => item.ref).sort()).toEqual(["read_entity", "run_manually"]);
    expect(found.find((item) => item.ref === "read_entity")?.schema?.properties).toHaveProperty(
      "rows",
    );
    expect(found.find((item) => item.ref === "run_manually")?.sample).toEqual({ test: "x" });
  });
});
