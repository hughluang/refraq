import { describe, expect, it } from "vitest";

import { formatRunSubject } from "@/features/channels/formatRunSubject";

const messages: Record<string, string> = {
  "channels.runs.subject.draft": "Draft",
  "channels.runs.subject.latest": "Latest published version",
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

  it("names a published run that has not resolved a version yet", () => {
    expect(formatRunSubject({ target: "published", version: null }, t)).toBe(
      "Latest published version",
    );
  });

  it("names a draft run without a revision number", () => {
    expect(formatRunSubject({ target: "draft", version: null }, t)).toBe(
      "Draft",
    );
  });
});
