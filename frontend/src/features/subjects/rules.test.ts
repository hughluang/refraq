import { describe, expect, it } from "vitest";

import {
  encodeSubjectDrafts,
  subjectKeyError,
  subjectNameError,
} from "@/features/subjects/rules";

describe("subject keys and names", () => {
  it("accepts a letter-led key and rejects an empty or illegal one", () => {
    expect(subjectKeyError("east_sales")).toBeNull();
    expect(subjectKeyError("")).toBe("required");
    expect(subjectKeyError("East")).toBe("charset");
    expect(subjectKeyError(`a${"b".repeat(63)}`)).toBe("charset");
  });

  it("requires a name of at most 256 characters", () => {
    expect(subjectNameError("  East sales  ")).toBeNull();
    expect(subjectNameError("   ")).toBe("required");
    expect(subjectNameError("n".repeat(257))).toBe("tooLong");
  });
});

describe("encodeSubjectDrafts", () => {
  it("omits empty keys, encodes integers, and rejects a second single value", () => {
    const encoded = encodeSubjectDrafts([
      {
        key: "regions",
        valueType: "dictionary",
        multiValue: true,
        texts: [" EAST ", "EAST", ""],
      },
      {
        key: "quota",
        valueType: "integer",
        multiValue: false,
        texts: ["12"],
      },
      {
        key: "note",
        valueType: "string",
        multiValue: false,
        texts: [" "],
      },
    ]);
    expect(encoded).toEqual({
      ok: true,
      values: { regions: ["EAST"], quota: [12] },
    });
    expect(
      encodeSubjectDrafts([
        {
          key: "owner",
          valueType: "user",
          multiValue: false,
          texts: ["user_a", "user_b"],
        },
      ]),
    ).toEqual({ ok: false, issue: { key: "owner", reason: "single" } });
  });

  it("rejects a bad date and an integer outside 64-bit range", () => {
    expect(
      encodeSubjectDrafts([
        {
          key: "hired",
          valueType: "date",
          multiValue: false,
          texts: ["2026-02-31"],
        },
      ]),
    ).toEqual({ ok: false, issue: { key: "hired", reason: "date" } });
    expect(
      encodeSubjectDrafts([
        {
          key: "quota",
          valueType: "integer",
          multiValue: false,
          texts: ["9223372036854775808"],
        },
      ]),
    ).toEqual({ ok: false, issue: { key: "quota", reason: "integer" } });
  });
});
