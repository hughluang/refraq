import { describe, expect, it } from "vitest";

import { formatHostBytes, formatHostMetric, formatHostNumber } from "@/features/host/format";

describe("Host metric formatting", () => {
  it("distinguishes missing counts from recorded zero and groups large counts by locale", () => {
    expect(formatHostNumber(null, "en-US")).toBe("—");
    expect(formatHostNumber(0, "en-US")).toBe("0");
    expect(formatHostNumber(1234567, "en-US")).toBe("1,234,567");
    expect(formatHostNumber(1234567, "zh-CN")).toBe("1,234,567");
    expect(formatHostNumber(0.0000001234, "en-US")).toBe("0.000000123");
    expect(formatHostNumber(2500.5, "en-US")).toBe("2,500.5");
  });

  it("scales bytes explicitly and preserves signed sample changes", () => {
    for (const locale of ["en-US", "zh-CN"]) {
      expect(formatHostBytes(null, locale)).toBe("—");
      expect(formatHostBytes(0, locale)).toBe("0 B");
      expect(formatHostBytes(1024, locale)).toBe("1 KiB");
      expect(formatHostBytes(1048576, locale)).toBe("1 MiB");
      expect(formatHostBytes(1073741824, locale)).toBe("1 GiB");
      expect(formatHostBytes(1099511627776, locale)).toBe("1 TiB");
      expect(formatHostBytes(-1536, locale, true)).toBe("-1.5 KiB");
      expect(formatHostBytes(1536, locale, true)).toBe("+1.5 KiB");
      expect(formatHostBytes(0, locale, true)).toBe("0 B");
      expect(formatHostBytes(0.000001, locale)).toBe("0.000001 B");
    }
  });

  it("keeps shares, CPU rates, step estimates and raw counters in their own unit families", () => {
    for (const locale of ["en-US", "zh-CN"]) {
      expect(formatHostMetric(null, "share", locale)).toBe("—");
      expect(formatHostMetric(0, "share", locale)).toBe("0%");
      expect(formatHostMetric(0.125, "share", locale)).toBe("12.5%");
      expect(formatHostMetric(0.00000001, "share", locale)).toBe("0.000001%");
      expect(formatHostMetric(0.25, "cpu-rate", locale)).toBe("0.25 CPU-s/s");
      expect(formatHostMetric(0.000001, "cpu-step", locale)).toBe("0.000001 CPU-s/step");
      expect(formatHostMetric(2500.5, "number", locale)).toBe("2,500.5");
      expect(formatHostMetric(-2048, "byte-change", locale)).toBe("-2 KiB");
      expect(formatHostMetric(4096, "bytes", locale)).toBe("4 KiB");
    }
  });
});
