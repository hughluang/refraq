import { describe, expect, it, vi } from "vitest";

import { listChannels } from "@/features/channels/api";
import { channelListRequest } from "@/features/channels/channelListFilter";

const EMPTY_PAGE = { items: [], total: 0, limit: 50, offset: 0 };

function jsonResponse(body: unknown) {
  return new Response(JSON.stringify(body), {
    status: 200,
    headers: { "Content-Type": "application/json" },
  });
}

describe("channel list filters", () => {
  it("opens with activation omitted and can choose or clear it", () => {
    const opening = channelListRequest({
      q: "",
      active: "",
      tagIds: [],
      limit: 50,
      offset: 0,
    });
    expect(opening).toEqual({ limit: 50, offset: 0 });
    expect(opening).not.toHaveProperty("active");
    expect(opening).not.toHaveProperty("tag_id");

    expect(
      channelListRequest({
        q: "",
        active: "true",
        tagIds: [],
        limit: 50,
        offset: 0,
      }),
    ).toEqual({ active: true, limit: 50, offset: 0 });

    expect(
      channelListRequest({
        q: "",
        active: "false",
        tagIds: [],
        limit: 50,
        offset: 0,
      }),
    ).toEqual({ active: false, limit: 50, offset: 0 });

    const cleared = channelListRequest({
      q: "",
      active: "",
      tagIds: [],
      limit: 50,
      offset: 0,
    });
    expect(cleared).not.toHaveProperty("active");
  });

  it("sends repeated tag ids and omits them when none are selected", async () => {
    const opening = channelListRequest({
      q: "  ",
      active: "",
      tagIds: [],
      limit: 50,
      offset: 0,
    });
    expect(opening).not.toHaveProperty("tag_id");
    expect(opening).not.toHaveProperty("active");

    const filtered = channelListRequest({
      q: "  Alpha ",
      active: "false",
      tagIds: ["tag_ledger", "tag_tax"],
      limit: 50,
      offset: 50,
    });
    expect(filtered).toEqual({
      q: "Alpha",
      active: false,
      tag_id: ["tag_ledger", "tag_tax"],
      limit: 50,
      offset: 50,
    });

    const fetchMock = vi.fn(async () => jsonResponse(EMPTY_PAGE));
    vi.stubGlobal("fetch", fetchMock);
    try {
      await listChannels(opening);
      const openingParams = new URL(
        String(fetchMock.mock.calls[0]?.[0]),
        "http://localhost",
      ).searchParams;
      expect(openingParams.has("active")).toBe(false);
      expect(openingParams.getAll("tag_id")).toEqual([]);

      await listChannels(filtered);
      const sent = new URL(
        String(fetchMock.mock.calls[1]?.[0]),
        "http://localhost",
      ).searchParams;
      expect(sent.getAll("tag_id")).toEqual(["tag_ledger", "tag_tax"]);
      expect(sent.get("active")).toBe("false");
      expect(sent.get("q")).toBe("Alpha");
    } finally {
      vi.unstubAllGlobals();
    }
  });
});
