import { describe, expect, it } from "vitest";

import {
  outputPaths,
  resolvedText,
  templateCompletions,
  templatePreview,
  templateRule,
  upstreamOutputs,
} from "@/features/channels/templateLogic";

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

describe("completion", () => {
  const upstream = [
    {
      ref: "read_entity",
      name: "Read entity",
      paths: outputPaths({ type: "object", properties: { rows: {}, count: {} } }),
    },
  ];

  it("suggests upstream refs inside an expression and not in literal text", () => {
    const inside = templateCompletions("{{ self.", 8, false, upstream);
    expect(inside?.options).toEqual(["self.read_entity"]);
    expect(templateCompletions("self.", 5, false, upstream)).toBeNull();
    expect(templateCompletions("{{ ", 3, true, upstream)?.options).toEqual(["self.read_entity"]);
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
      templateCompletions(partial, partial.length, true, [
        ...upstream,
        { ref: "hold", name: "Hold", paths: ["output"] },
      ])?.options,
    ).toEqual(['self.nodes["Hold"]']);
  });

  it("suggests refs on an explicit invoke inside empty braces", () => {
    const text = "{{  }}";
    const found = templateCompletions(text, 3, true, upstream);
    expect(found?.options).toEqual(["self.read_entity"]);
    expect(templateCompletions(text, 3, false, upstream)).toBeNull();
  });

  it("suggests output fields from the start of the path", () => {
    const text = "{{ self.read_entity.output.";
    expect(templateCompletions(text, text.length, false, upstream)).toEqual({
      from: 3,
      options: [
        "self.read_entity.output",
        "self.read_entity.output.rows",
        "self.read_entity.output.count",
      ],
    });
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
    );
    expect(found.map((item) => item.ref).sort()).toEqual(["read_entity", "run_manually"]);
    expect(found.find((item) => item.ref === "read_entity")?.paths).toContain("output.rows");
  });
});
