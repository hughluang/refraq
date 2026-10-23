import { describe, expect, it } from "vitest";

import {
  batchOrdWindow,
  datasetReferencesIn,
  datasetRowLimit,
  latestExecutionQuery,
  readBatchOutput,
  rowsInsideWindow,
  soleStatus,
} from "@/features/channels/datasetView";

const reference = {
  dataset_id: "dst_1",
  columns: [{ name: "code", type: "string" }],
  count: 2500,
};

describe("dataset references", () => {
  it("finds a nested reference and ignores an anonymous string", () => {
    expect(datasetReferencesIn({ dataset: reference, count: 2500 })).toEqual([reference]);
    expect(datasetReferencesIn({ dataset_id: "dst_1" })).toEqual([]);
    expect(datasetReferencesIn("dst_1")).toEqual([]);
  });
});

describe("batch ord window", () => {
  it("selects the round window and caps the page at 200 rows", () => {
    // Round 1 of batch 1000 is _ord in (1000, 2000], and total 2500 does not shorten it.
    expect(batchOrdWindow(1, 1000, 2500)).toEqual({ afterOrd: 1000, endOrd: 2000 });
    expect(datasetRowLimit(1000, 2000)).toBe(200);
    expect(datasetRowLimit(1900, 2000)).toBe(100);
    expect(datasetRowLimit(2000, 2000)).toBeNull();
    // The last round stops at total, not at the nominal end.
    expect(batchOrdWindow(2, 1000, 2500)).toEqual({ afterOrd: 2000, endOrd: 2500 });
  });

  it("hides rows that fall past the window", () => {
    expect(rowsInsideWindow([{ _ord: 1001 }, { _ord: 2000 }, { _ord: 2001 }], 2000)).toEqual([
      { _ord: 1001 },
      { _ord: 2000 },
    ]);
  });
});

describe("latest execution query", () => {
  it("asks for one execution at the last offset, not the whole history", () => {
    expect(
      latestExecutionQuery({
        node_id: "batch",
        execution_count: 3,
        status_counts: { succeeded: 2, failed: 1 },
      }),
    ).toEqual({ node_id: "batch", limit: 1, offset: 2 });
    expect(
      latestExecutionQuery({ node_id: "idle", execution_count: 0, status_counts: {} }),
    ).toBeNull();
    expect(soleStatus({ succeeded: 2 })).toBe("succeeded");
    expect(soleStatus({ succeeded: 2, failed: 1 })).toBeNull();
  });
});

describe("batch output", () => {
  it("reads batch size and total from the stored container output", () => {
    expect(readBatchOutput({ count: 3, total: 2500, batch_size: 1000 })).toEqual({
      batchSize: 1000,
      total: 2500,
    });
    expect(readBatchOutput({ rows: [] })).toBeNull();
  });
});
