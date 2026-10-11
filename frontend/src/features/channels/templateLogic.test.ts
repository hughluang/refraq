import { describe, expect, it } from "vitest";

import {
  applyCompletion,
  completionLabels,
  completionQuery,
  hasCalculation,
  outputPaths,
  resolvedText,
  templatePreview,
  templateRule,
  upstreamOutputs,
} from "@/features/channels/templateLogic";

const LIST = { type: "array", items: { type: "object" } } as const;

describe("templatePreview", () => {
  it("accepts static JSON for a list without braces", () => {
    expect(hasCalculation('[{"sku": "BT-abc"}]')).toBe(false);
    expect(templatePreview('[{"sku": "BT-abc"}]', LIST).state).toBe("ok");
  });

  it("rejects static text that is not the declared type", () => {
    expect(templatePreview("not-json", LIST).state).toBe("error");
  });

  it("defers a calculation", () => {
    expect(templatePreview('abc{{ "def" }}', { type: "string" }).state).toBe("deferred");
  });

  it("treats an escaped brace as static text", () => {
    expect(hasCalculation("\\{{ not code }}")).toBe(false);
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
    { ref: "read_entity", paths: outputPaths({ type: "object", properties: { rows: {}, count: {} } }) },
  ];

  it("suggests upstream refs after self.", () => {
    const query = completionQuery("{{ self.", 8);
    expect(query?.kind).toBe("ref");
    expect(query ? completionLabels(query, upstream) : []).toEqual(["read_entity"]);
  });

  it("suggests output fields and inserts the chosen path", () => {
    const text = "{{ self.read_entity.output.";
    const query = completionQuery(text, text.length);
    expect(query?.kind).toBe("path");
    expect(query ? completionLabels(query, upstream) : []).toEqual(["output", "output.rows", "output.count"]);
    if (!query) return;
    const applied = applyCompletion(text, text.length, query, "output.rows");
    expect(applied.next).toBe("{{ self.read_entity.output.rows");
  });
});

describe("upstreamOutputs", () => {
  it("lists ancestors and not the node itself", () => {
    const found = upstreamOutputs(
      "write",
      [
        { id: "trigger", ref: "run_manually" },
        { id: "read", ref: "read_entity" },
        { id: "write", ref: "write_entity" },
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
