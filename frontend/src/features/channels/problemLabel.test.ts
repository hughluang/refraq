import { describe, expect, it } from "vitest";

import { formatRunError } from "@/features/channels/problemLabel";

const LABELS: Record<string, string> = {
  "problems.CHANNEL_VALUE_TYPE_MISMATCH": "A template result does not match its declared type",
};

const t = (key: string) => LABELS[key] ?? key;

describe("formatRunError", () => {
  it("uses the locale label and keeps the occurrence text", () => {
    expect(
      formatRunError(t, "CHANNEL_VALUE_TYPE_MISMATCH", "Value does not match the declared type"),
    ).toEqual({
      label: "A template result does not match its declared type",
      detail: "Value does not match the declared type",
    });
  });

  it("falls back to the message when the code has no locale", () => {
    expect(formatRunError(t, "CHANNEL_NODE_FAILED", "import of os is not allowed")).toEqual({
      label: "import of os is not allowed",
      detail: null,
    });
  });

  it("returns an empty label when nothing is known", () => {
    expect(formatRunError(t, null, null)).toEqual({ label: "", detail: null });
  });
});
