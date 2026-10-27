import { describe, expect, it } from "vitest";

import { ApiError } from "@/lib/api";
import { bulkTagFailureMessage } from "@/features/tags/bulkTagFailure";

const LABELS: Record<string, string> = {
  "problems.TAG_LIMIT_EXCEEDED": "A record can carry at most ten Tags.",
  "problems.TAG_NOT_FOUND": "Tag was not found",
  "problems.unknown": "Something went wrong. Try again.",
  "tags.bulk.wroteNothing": "None of the checked rows were changed.",
  "tags.bulk.nameSeparator": ", ",
  "tags.bulk.refused": "{{lead}} {{unchanged}}",
  "tags.bulk.refusedNamed": "{{lead}} {{names}}. {{unchanged}}",
};

function t(key: string, values?: Record<string, string>): string {
  const template = LABELS[key] ?? key;
  if (!values) return template;
  return template.replace(/\{\{(\w+)\}\}/g, (_, name: string) => values[name] ?? "");
}

describe("bulkTagFailureMessage", () => {
  it("names the records on this page and states that nothing was written", () => {
    const error = new ApiError(422, "TAG_LIMIT_EXCEEDED", "A record can carry at most ten Tags", null, {
      subjects: [
        { kind: "entity", id: "ent_full" },
        { kind: "entity", id: "ent_other" },
      ],
    });
    const message = bulkTagFailureMessage(
      t,
      error,
      new Map([
        ["ent_full", "Alpha"],
        ["ent_other", "Beta"],
      ]),
    );
    expect(message).toBe(
      "A record can carry at most ten Tags. Alpha, Beta. None of the checked rows were changed.",
    );
    expect(message).not.toBe("A record can carry at most ten Tags");
  });

  it("states that nothing was written when the Problem has no subjects", () => {
    const error = new ApiError(404, "TAG_NOT_FOUND", "Tag was not found");
    expect(bulkTagFailureMessage(t, error, new Map())).toBe(
      "Tag was not found None of the checked rows were changed.",
    );
  });

  it("does not claim the request wrote nothing for a transport failure", () => {
    const message = bulkTagFailureMessage(t, new Error("network"), new Map([["ent_full", "Alpha"]]));
    expect(message).toBe("Error: network");
    expect(message).not.toContain("None of the checked rows were changed.");
  });
});