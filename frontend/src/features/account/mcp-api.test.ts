import { describe, expect, it } from "vitest";

import { mcpClientConfig } from "@/features/account/mcp-api";

describe("mcpClientConfig", () => {
  it("uses a PAT placeholder, not a live token", () => {
    const text = mcpClientConfig("https://console.example.com", "/mcp");
    expect(text).toContain("https://console.example.com/mcp");
    expect(text).toContain("Bearer <YOUR_TOKEN>");
    expect(text).not.toContain("refraq_");
  });
});
