/** @vitest-environment jsdom */

import { act, renderHook } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { useCatalogSample } from "@/features/sources/catalog-detail/useCatalogSample";
import { runObjectSample } from "@/features/sources/api/sample";
import type { CatalogObject } from "@/features/sources/types";

const open = vi.hoisted(() => vi.fn());

vi.mock("@refinedev/core", () => ({
  useTranslate: () => (key: string) => key,
  useNotification: () => ({ open }),
  useCan: () => ({ data: { can: true }, isLoading: false }),
}));

vi.mock("@/features/sources/api/sample", () => ({
  runObjectSample: vi.fn(),
}));

const object = {
  id: "obj_1",
  object_type: "table",
  primary_key: ["id"],
  columns: [
    { name: "id", is_present: true },
    { name: "seen_at", is_present: true },
  ],
} as CatalogObject;

describe("useCatalogSample", () => {
  beforeEach(() => {
    vi.mocked(runObjectSample).mockReset();
    open.mockReset();
  });

  it("does not submit a filter that exceeds precision declared on the sample response", async () => {
    vi.mocked(runObjectSample).mockResolvedValue({
      columns: ["seen_at"],
      declarations: [
        {
          name: "seen_at",
          temporal_kind: "time",
          precision: 3,
          nullable: true,
        },
      ],
      rows: [["01:02:03.123"]],
      truncated: false,
      duration_ms: 1,
      offset: 0,
      limit: 50,
      has_more: false,
    });
    const { result } = renderHook(() => useCatalogSample(object));

    await act(async () => {
      await result.current.run(0);
    });
    expect(runObjectSample).toHaveBeenCalledTimes(1);

    act(() => {
      result.current.setFilter({
        column: "seen_at",
        op: "eq",
        value: "01:02:03.1234",
      });
    });
    await act(async () => {
      await result.current.run(0);
    });

    expect(runObjectSample).toHaveBeenCalledTimes(1);
    expect(open).toHaveBeenCalledWith({
      type: "error",
      message: "catalog.sample.precision",
    });
  });
});
