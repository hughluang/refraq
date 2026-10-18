import { describe, expect, it } from "vitest";

import {
  formatFailedNode,
  formatRunSubject,
  nodeDisplayName,
} from "@/features/channels/formatRunSubject";

const messages: Record<string, string> = {
  "channels.runs.subject.draft": "Draft",
  "channels.runs.subject.version": "Version {{number}}",
};

const t = (key: string, options?: Record<string, unknown>) => {
  const template = messages[key] ?? key;
  if (!options) return template;
  return template.replace(/\{\{(\w+)\}\}/g, (_, name: string) =>
    String(options[name] ?? ""),
  );
};

describe("formatRunSubject", () => {
  it("names a resolved published version", () => {
    expect(formatRunSubject({ target: "published", version: 3 }, t)).toBe(
      "Version 3",
    );
  });

  it("omits a published run that has not resolved a version yet", () => {
    expect(formatRunSubject({ target: "published", version: null }, t)).toBe("");
  });

  it("names a draft run without a revision number", () => {
    expect(formatRunSubject({ target: "draft", version: null }, t)).toBe(
      "Draft",
    );
  });
});

describe("formatFailedNode", () => {
  it("uses the graph name", () => {
    expect(formatFailedNode([{ id: "nd_write", name: "Write rows" }], "nd_write")).toBe(
      "Write rows",
    );
  });

  it("uses the id when the graph has no name", () => {
    expect(formatFailedNode([{ id: "nd_write", name: "  " }], "nd_write")).toBe("nd_write");
    expect(formatFailedNode([], "nd_missing")).toBe("nd_missing");
  });

  it("returns null when the run did not fail a node", () => {
    expect(formatFailedNode([], null)).toBeNull();
  });
});

describe("nodeDisplayName", () => {
  it("prefers the node name, then its ref, then the id", () => {
    const nodes = [
      { id: "nd_1", name: "Read rows", ref: "read" },
      { id: "nd_2", name: "  ", ref: "write" },
      { id: "nd_3", name: "", ref: "" },
    ];
    expect(nodeDisplayName(nodes, "nd_1")).toBe("Read rows");
    expect(nodeDisplayName(nodes, "nd_2")).toBe("write");
    expect(nodeDisplayName(nodes, "nd_3")).toBe("nd_3");
    expect(nodeDisplayName(nodes, null)).toBeNull();
  });
});
