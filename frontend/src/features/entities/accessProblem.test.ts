import { describe, expect, it } from "vitest";

import { accessProblemText } from "@/features/entities/accessProblem";
import { ApiError } from "@/lib/api";

const t = (key: string) => key;

describe("accessProblemText", () => {
  it("turns a subject-attribute rule rejection into copy and drops the path", () => {
    const text = accessProblemText(
      new ApiError(422, "ENTITY_ACCESS_INVALID", "$.and[0].eq: subject_attr is only valid for in"),
      t,
    );
    expect(text).toBe("entities.access.rule.reject.subjectAttr");
    expect(text.includes("$")).toBe(false);
  });

  it("keeps a non-rule invalid detail", () => {
    expect(
      accessProblemText(new ApiError(422, "ENTITY_ACCESS_INVALID", "write without read"), t),
    ).toBe("write without read");
  });
});
