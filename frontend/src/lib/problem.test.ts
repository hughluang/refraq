import { describe, expect, it } from "vitest";

import { ApiError } from "@/lib/api";
import { problemMessage } from "@/lib/problem";

const dictionary: Record<string, string> = {
  "problems.USER_GROUP_KEY_DUPLICATE": "That user group key is taken",
  "problems.unknown": "Something went wrong",
};

function t(key: string): string {
  return dictionary[key] ?? key;
}

describe("problemMessage", () => {
  it("uses the Problem Code entry when one exists", () => {
    const error = new ApiError(
      409,
      "USER_GROUP_KEY_DUPLICATE",
      "User Group key already exists",
    );
    expect(problemMessage(t, error, "failed")).toBe("That user group key is taken");
  });

  it("does not return raw English detail when a code is unknown", () => {
    const error = new ApiError(
      422,
      "ENTITY_ROW_INVALID",
      "Entity row values or filters are invalid",
    );
    expect(problemMessage(t, error, "failed")).toBe("Something went wrong");
    expect(problemMessage(t, error, "failed")).not.toBe(
      "Entity row values or filters are invalid",
    );
  });

  it("uses the caller fallback when the failure is not an API error", () => {
    expect(problemMessage(t, new Error("nope"), "load failed")).toBe("load failed");
  });
});
