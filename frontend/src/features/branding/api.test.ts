import { afterEach, describe, expect, it, vi } from "vitest";

import { fetchPublicBranding, resetBranding } from "@/features/branding/api";
import { DEFAULT_BRANDING } from "@/features/branding/types";

const PUBLIC = {
  ...DEFAULT_BRANDING,
  brand_names: { "en-US": "Acme" },
};

describe("branding api cache", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("reads public branding without storing the response", async () => {
    const fetchMock = vi.fn(async () => {
      return new Response(JSON.stringify(PUBLIC), {
        status: 200,
        headers: { "Content-Type": "application/json" },
      });
    });
    vi.stubGlobal("fetch", fetchMock);

    await expect(fetchPublicBranding()).resolves.toEqual(PUBLIC);
    expect(fetchMock).toHaveBeenCalledWith(
      "/api/branding",
      expect.objectContaining({ cache: "no-store" }),
    );
  });

  it("refetches without store after reset", async () => {
    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce(
        new Response(null, { status: 204 }),
      )
      .mockResolvedValueOnce(
        new Response(JSON.stringify(DEFAULT_BRANDING), {
          status: 200,
          headers: { "Content-Type": "application/json" },
        }),
      );
    vi.stubGlobal("fetch", fetchMock);

    await expect(resetBranding()).resolves.toEqual(DEFAULT_BRANDING);
    expect(fetchMock).toHaveBeenNthCalledWith(
      2,
      "/api/branding",
      expect.objectContaining({ cache: "no-store" }),
    );
  });
});
