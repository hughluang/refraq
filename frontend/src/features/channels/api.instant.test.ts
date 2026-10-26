import { afterEach, describe, expect, it, vi } from "vitest";

import { listRounds, nodeSample } from "@/features/channels/api";
import { EMPTY_GRAPH } from "@/features/channels/types";

function jsonResponse(body: unknown) {
  return new Response(JSON.stringify(body), {
    status: 200,
    headers: { "Content-Type": "application/json" },
  });
}

describe("node sample and rounds success bodies", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("returns a node sample that the time table does not list", async () => {
    const body = {
      scope: [],
      config_changed: false,
      upstream: [],
      node: {
        state: "ok",
        seq: 3,
        status: "succeeded",
        output: { kept: true },
        output_truncated: false,
        totals: {},
        input: null,
        input_totals: null,
        error: null,
        preview_only: false,
      },
    };
    vi.stubGlobal(
      "fetch",
      vi.fn(async () => jsonResponse(body)),
    );

    await expect(
      nodeSample("chn_1", "job_1", { graph: EMPTY_GRAPH, node_id: "write" }),
    ).resolves.toEqual(body);
  });

  it("returns rounds that the time table does not list", async () => {
    const body = {
      items: [
        {
          round: 0,
          step_preview: { n: 1 },
          step_truncated: false,
          step_totals: {},
          status_counts: { succeeded: 1 },
        },
      ],
      total: 1,
      limit: 50,
      offset: 0,
    };
    vi.stubGlobal(
      "fetch",
      vi.fn(async () => jsonResponse(body)),
    );

    await expect(
      listRounds("chn_1", "job_1", 4, { limit: 50, offset: 0 }),
    ).resolves.toEqual(body);
  });
});
