import { describe, expect, it } from "vitest";

import {
  scheduleIdentity,
  scheduleIdentityLabel,
} from "@/features/schedules/scheduleIdentity";
import type { ScheduleIdentityInput } from "@/features/schedules/scheduleIdentity";

function task(
  overrides: Partial<ScheduleIdentityInput> = {},
): ScheduleIdentityInput {
  return {
    name: "structure · mes-prod",
    work_kind: "structure",
    target: { source_id: "src_1", source_key: "mes-prod" },
    ...overrides,
  };
}

describe("scheduleIdentity", () => {
  it("hides a platform default name and shows kind plus source key", () => {
    expect(scheduleIdentity(task(), "platform")).toEqual({
      primary: "structure · mes-prod",
      customName: null,
    });
  });

  it("shows a renamed schedule under the kind line", () => {
    expect(
      scheduleIdentity(task({ name: "nightly structure" }), "platform"),
    ).toEqual({
      primary: "structure · mes-prod",
      customName: "nightly structure",
    });
  });

  it("shows catalog embed as the raw kind and hides its default name", () => {
    expect(
      scheduleIdentity(
        task({
          name: "catalog embed",
          work_kind: "catalog_embed",
          target: null,
        }),
        "platform",
      ),
    ).toEqual({ primary: "catalog_embed", customName: null });
  });

  it("shows a renamed catalog embed name on the second line", () => {
    expect(
      scheduleIdentity(
        task({
          name: "nightly embed",
          work_kind: "catalog_embed",
          target: null,
        }),
        "platform",
      ),
    ).toEqual({ primary: "catalog_embed", customName: "nightly embed" });
  });

  it("omits the target on a source workbench", () => {
    expect(
      scheduleIdentity(
        task({
          name: "join_detection · mes-prod",
          work_kind: "join_detection",
        }),
        "source",
      ),
    ).toEqual({ primary: "join_detection", customName: null });
  });

  it("keeps a custom name on the source workbench", () => {
    expect(
      scheduleIdentity(
        task({ name: "slow join", work_kind: "join_detection" }),
        "source",
      ),
    ).toEqual({ primary: "join_detection", customName: "slow join" });
  });

  it("falls back to source id when the key is missing", () => {
    expect(
      scheduleIdentity(
        task({
          name: "structure · src_1",
          target: { source_id: "src_1", source_key: null },
        }),
        "platform",
      ),
    ).toEqual({ primary: "structure · src_1", customName: null });
  });

  it("keeps a historical default name when the source key is gone", () => {
    expect(
      scheduleIdentity(
        task({
          name: "structure · mes-prod",
          target: { source_id: "src_1", source_key: null },
        }),
        "platform",
      ),
    ).toEqual({
      primary: "structure · src_1",
      customName: "structure · mes-prod",
    });
  });

});

describe("scheduleIdentityLabel", () => {
  it("appends a custom name after the primary line", () => {
    expect(
      scheduleIdentityLabel(task({ name: "nightly structure" }), "platform"),
    ).toBe("structure · mes-prod · nightly structure");
  });

  it("is the primary line when the name is the default", () => {
    expect(scheduleIdentityLabel(task(), "platform")).toBe(
      "structure · mes-prod",
    );
  });
});
