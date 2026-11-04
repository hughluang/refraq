import { describe, expect, it } from "vitest";

import {
  formatCeilingGigabytes,
  formatDatasetGigabytes,
} from "@/features/channel-dataset-usage/gigabytes";

describe("formatDatasetGigabytes", () => {
  it("rounds half away from zero to one decimal and drops a trailing .0", () => {
    expect(formatDatasetGigabytes(0)).toBe("0");
    expect(formatDatasetGigabytes(1073741824)).toBe("1");
    expect(formatDatasetGigabytes(1342177280)).toBe("1.3");
    expect(formatDatasetGigabytes(68987912192)).toBe("64.3");
  });
});

describe("formatCeilingGigabytes", () => {
  it("prints the ceiling as a whole number of gigabytes", () => {
    expect(formatCeilingGigabytes(107374182400)).toBe("100");
  });
});
