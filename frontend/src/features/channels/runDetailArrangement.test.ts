import { describe, expect, it } from "vitest";

import {
  RUN_DETAIL_BAND_MIN_REM,
  RUN_DETAIL_COLUMNS_MIN_REM,
  runDetailArrangement,
} from "@/features/channels/runDetailArrangement";

describe("runDetailArrangement", () => {
  const font = 16;

  it("places three panes on one row at 64rem and just above", () => {
    expect(runDetailArrangement(RUN_DETAIL_COLUMNS_MIN_REM * font, font)).toBe("columns");
    expect(runDetailArrangement(RUN_DETAIL_COLUMNS_MIN_REM * font + 1, font)).toBe("columns");
  });

  it("keeps the index under the graph just below 64rem", () => {
    expect(runDetailArrangement(RUN_DETAIL_COLUMNS_MIN_REM * font - 1, font)).toBe("band");
  });

  it("keeps the index under the graph at the graph-and-inspector floor", () => {
    expect(runDetailArrangement(RUN_DETAIL_BAND_MIN_REM * font, font)).toBe("band");
  });

  it("stacks the panes when the graph and the inspector cannot sit side by side", () => {
    expect(runDetailArrangement(RUN_DETAIL_BAND_MIN_REM * font - 1, font)).toBe("stack");
    expect(runDetailArrangement(0, font)).toBe("stack");
  });

  it("reads rem from the root font size", () => {
    const root = 20;
    expect(runDetailArrangement(RUN_DETAIL_COLUMNS_MIN_REM * root, root)).toBe("columns");
    expect(runDetailArrangement(RUN_DETAIL_COLUMNS_MIN_REM * root - 1, root)).toBe("band");
    expect(runDetailArrangement(RUN_DETAIL_BAND_MIN_REM * root - 1, root)).toBe("stack");
  });

  it("falls back to a 16px rem when the root font is not positive", () => {
    expect(runDetailArrangement(RUN_DETAIL_COLUMNS_MIN_REM * 16, 0)).toBe("columns");
    expect(runDetailArrangement(RUN_DETAIL_BAND_MIN_REM * 16 - 1, -2)).toBe("stack");
  });
});
