import { describe, expect, it } from "vitest";

import { scanTemplate } from "@/features/channels/templateScan";

function marked(text: string, kind: "delim" | "ref" | "node"): string[] {
  return scanTemplate(text)
    .marks.filter((mark) => mark.kind === kind)
    .map((mark) => text.slice(mark.from, mark.to));
}

describe("scanTemplate", () => {
  it("keeps a quoted closer inside one expression", () => {
    const text = '{{ "a}}" }}';
    const scanned = scanTemplate(text);
    expect(scanned.ok).toBe(true);
    expect(scanned.wholeExpression).toBe(true);
    expect(scanned.expressions).toHaveLength(1);
    expect(text.slice(scanned.expressions[0]?.bodyFrom, scanned.expressions[0]?.bodyTo)).toBe(' "a}}" ');
    expect(marked(text, "delim")).toEqual(["{{", "}}"]);
  });

  it("treats an escaped opener as text", () => {
    const scanned = scanTemplate("\\{{ not code }}");
    expect(scanned.ok).toBe(true);
    expect(scanned.hasExpression).toBe(false);
    expect(scanned.marks).toEqual([]);
    expect(scanned.staticText).toBe("{{ not code }}");
    expect(scanTemplate("  \\{{ not code }}  ").staticText).toBe("{{ not code }}");
  });

  it("marks a ref and a node name", () => {
    const ref = "{{ self.read.output.rows }}";
    expect(marked(ref, "ref")).toEqual(["self.read"]);
    const named = '{{ self.nodes["Read suppliers"].output }}';
    expect(marked(named, "node")).toEqual(['self.nodes["Read suppliers"]']);
    expect(marked("{{ self.channel.id }}", "ref")).toEqual([]);
  });

  it("shifts marks by leading whitespace", () => {
    const text = "  {{ self.read }}";
    const scanned = scanTemplate(text);
    expect(scanned.wholeExpression).toBe(true);
    expect(marked(text, "ref")).toEqual(["self.read"]);
  });

  it("keeps an unclosed expression open for decoration", () => {
    const text = "{{ self.read";
    const scanned = scanTemplate(text);
    expect(scanned.ok).toBe(false);
    expect(scanned.hasExpression).toBe(false);
    expect(marked(text, "delim")).toEqual(["{{"]);
    expect(marked(text, "ref")).toEqual(["self.read"]);
  });

  it("does not mark a ref written inside a string", () => {
    expect(marked('{{ "self.read" }}', "ref")).toEqual([]);
  });

  it("keeps a trailing space inside an open expression", () => {
    const text = "{{ ";
    const scanned = scanTemplate(text);
    expect(scanned.ok).toBe(false);
    expect(scanned.wholeExpression).toBe(false);
    expect(scanned.expressions[0]).toMatchObject({ from: 0, to: 3, bodyFrom: 2, bodyTo: 3 });
  });

  it("treats surrounding whitespace as one whole expression", () => {
    const text = "  {{ 1 }}  ";
    const scanned = scanTemplate(text);
    expect(scanned.wholeExpression).toBe(true);
    expect(scanned.expressions[0]).toMatchObject({ from: 2, to: text.trimEnd().length });
  });
});
