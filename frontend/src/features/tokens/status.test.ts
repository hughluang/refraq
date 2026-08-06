import { describe, expect, it } from "vitest";

import { tokenStatus } from "@/features/tokens/status";
import type { TokenMetadata } from "@/features/tokens/types";

function token(overrides: Partial<TokenMetadata> = {}): TokenMetadata {
  return {
    id: "pat_01",
    name: "mcp-local",
    prefix: "rfq_pat_ab12",
    expires_at: "2026-11-05T00:00:00Z",
    revoked_at: null,
    created_at: "2026-08-05T01:00:00Z",
    last_used_at: null,
    ...overrides,
  };
}

describe("tokenStatus", () => {
  const now = new Date("2026-08-06T00:00:00Z");

  it("returns active when not revoked and not expired", () => {
    expect(tokenStatus(token(), now)).toBe("active");
  });

  it("returns revoked when revoked_at is set", () => {
    expect(
      tokenStatus(token({ revoked_at: "2026-08-06T00:00:00Z" }), now),
    ).toBe("revoked");
  });

  it("returns expired when past expires_at", () => {
    expect(
      tokenStatus(token({ expires_at: "2026-08-05T00:00:00Z" }), now),
    ).toBe("expired");
  });

  it("prefers revoked over expired", () => {
    expect(
      tokenStatus(
        token({
          expires_at: "2026-08-05T00:00:00Z",
          revoked_at: "2026-08-04T00:00:00Z",
        }),
        now,
      ),
    ).toBe("revoked");
  });
});
