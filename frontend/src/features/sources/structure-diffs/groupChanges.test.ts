import { describe, expect, it } from "vitest";

import { groupChanges } from "@/features/sources/structure-diffs/groupChanges";

describe("groupChanges", () => {
  it("groups by change kind and keeps breaking kinds first", () => {
    const groups = groupChanges([
      { change: "fk_added", locator_key: "obj/a" },
      { change: "column_removed", locator_key: "col/x" },
      { change: "object_removed", locator_key: "obj/a" },
      { change: "fk_added", locator_key: "obj/b" },
    ]);
    expect(groups.map((g) => g.change)).toEqual([
      "object_removed",
      "column_removed",
      "fk_added",
    ]);
    expect(groups[2]?.items).toHaveLength(2);
  });

  it("keeps unknown change kinds after the known order", () => {
    const groups = groupChanges([
      { change: "custom_kind", locator_key: "x" },
      { change: "object_added", locator_key: "obj/a" },
    ]);
    expect(groups.map((g) => g.change)).toEqual([
      "object_added",
      "custom_kind",
    ]);
  });
});
