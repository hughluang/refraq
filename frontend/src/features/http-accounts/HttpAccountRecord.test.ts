import { describe, expect, it } from "vitest";

import { blankSecretKeeps } from "@/features/http-accounts/HttpAccountRecord";

const bearer = { authType: "bearer" as const, username: "" };
const basic = { authType: "basic" as const, username: "ada" };

describe("blankSecretKeeps", () => {
  it("keeps a blank secret only while the auth identity is unchanged", () => {
    expect(blankSecretKeeps("bearer", "", bearer)).toBe(true);
    expect(blankSecretKeeps("basic", "ada", basic)).toBe(true);
    expect(blankSecretKeeps("basic", "", bearer)).toBe(false);
    expect(blankSecretKeeps("basic", "other", basic)).toBe(false);
    expect(blankSecretKeeps("bearer", "", null)).toBe(false);
  });
});