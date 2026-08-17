import { describe, expect, it } from "vitest";

import {
  isAllowedTimeoutInput,
  timeoutFromTask,
  timeoutPayload,
} from "@/features/schedules/runningTimeoutField";

describe("timeoutFromTask", () => {
  it("maps null and absent to empty", () => {
    expect(timeoutFromTask(null)).toBe("");
    expect(timeoutFromTask(undefined)).toBe("");
  });

  it("keeps a stored second count including zero", () => {
    expect(timeoutFromTask(120)).toBe(120);
    expect(timeoutFromTask(0)).toBe(0);
  });
});

describe("timeoutPayload", () => {
  it("maps empty to null and passes numbers through", () => {
    expect(timeoutPayload("")).toBeNull();
    expect(timeoutPayload(120)).toBe(120);
    expect(timeoutPayload(0)).toBe(0);
  });
});

describe("isAllowedTimeoutInput", () => {
  it("allows empty and positive integers", () => {
    expect(isAllowedTimeoutInput("")).toBe(true);
    expect(isAllowedTimeoutInput(1)).toBe(true);
    expect(isAllowedTimeoutInput(90)).toBe(true);
  });

  it("rejects zero, non-integers, and non-finite numbers", () => {
    expect(isAllowedTimeoutInput(0)).toBe(false);
    expect(isAllowedTimeoutInput(-1)).toBe(false);
    expect(isAllowedTimeoutInput(1.5)).toBe(false);
    expect(isAllowedTimeoutInput(Number.NaN)).toBe(false);
    expect(isAllowedTimeoutInput(Number.POSITIVE_INFINITY)).toBe(false);
  });
});
