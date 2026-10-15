import { describe, expect, it } from "vitest";

import { canAuthorNodeType } from "@/features/channels/nodePermission";

describe("canAuthorNodeType", () => {
  it("allows a type that declares no extra permission", () => {
    expect(canAuthorNodeType(null, [])).toBe(true);
    expect(canAuthorNodeType(undefined, undefined)).toBe(true);
    expect(canAuthorNodeType("", ["channel:code_write"])).toBe(true);
  });

  it("allows a guarded type only when the session list includes that permission", () => {
    expect(
      canAuthorNodeType("channel:code_write", ["channel:write", "channel:code_write"]),
    ).toBe(true);
    expect(canAuthorNodeType("channel:source_query", ["channel:source_query"])).toBe(true);
    expect(canAuthorNodeType("channel:code_write", ["channel:write"])).toBe(false);
    expect(canAuthorNodeType("channel:source_query", [])).toBe(false);
    expect(canAuthorNodeType("channel:source_query", undefined)).toBe(false);
    expect(canAuthorNodeType("channel:code_write", null)).toBe(false);
  });
});
