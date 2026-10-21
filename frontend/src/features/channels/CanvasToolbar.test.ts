/** @vitest-environment jsdom */

import { afterEach, describe, expect, it, vi } from "vitest";

import {
  MINIMAP_STORAGE_KEY,
  readMinimapOpen,
  writeMinimapOpen,
} from "@/features/channels/CanvasToolbar";

describe("channel canvas minimap preference", () => {
  afterEach(() => {
    localStorage.removeItem(MINIMAP_STORAGE_KEY);
    vi.restoreAllMocks();
  });

  it("stays off until this browser stores it on", () => {
    localStorage.removeItem(MINIMAP_STORAGE_KEY);
    expect(readMinimapOpen()).toBe(false);
    writeMinimapOpen(true);
    expect(localStorage.getItem(MINIMAP_STORAGE_KEY)).toBe("1");
    expect(readMinimapOpen()).toBe(true);
    writeMinimapOpen(false);
    expect(readMinimapOpen()).toBe(false);
  });

  it("treats blocked storage as the default off state", () => {
    vi.spyOn(Storage.prototype, "getItem").mockImplementation(() => {
      throw new Error("denied");
    });
    expect(readMinimapOpen()).toBe(false);
    vi.spyOn(Storage.prototype, "setItem").mockImplementation(() => {
      throw new Error("denied");
    });
    expect(() => writeMinimapOpen(true)).not.toThrow();
  });
});
