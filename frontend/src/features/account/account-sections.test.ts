/** @vitest-environment jsdom */

import { afterEach, describe, expect, it, vi } from "vitest";

import {
  ACCOUNT_SECTION,
  activeAccountSection,
  observationFromEntry,
  scrollAccountSection,
} from "@/features/account/account-sections";

describe("scrollAccountSection", () => {
  afterEach(() => {
    document.body.replaceChildren();
    window.location.hash = "";
    vi.restoreAllMocks();
  });

  it("scrolls the target into view and does not write a hash", () => {
    const target = document.createElement("div");
    target.id = ACCOUNT_SECTION.mcp;
    document.body.append(target);
    const scrollIntoView = vi.fn();
    target.scrollIntoView = scrollIntoView;

    scrollAccountSection(ACCOUNT_SECTION.mcp);

    expect(scrollIntoView).toHaveBeenCalledWith({
      behavior: "smooth",
      block: "start",
    });
    expect(window.location.hash).toBe("");
  });

  it("does nothing when the target is missing", () => {
    expect(() => scrollAccountSection(ACCOUNT_SECTION.tokens)).not.toThrow();
    expect(window.location.hash).toBe("");
  });
});

describe("activeAccountSection", () => {
  it("returns null when nothing has been observed", () => {
    expect(activeAccountSection([])).toBeNull();
  });

  it("keeps the intersecting section whose top is closest to the root from above", () => {
    expect(
      activeAccountSection([
        {
          id: ACCOUNT_SECTION.profile,
          intersectionRatio: 0.2,
          top: -400,
        },
        {
          id: ACCOUNT_SECTION.tokens,
          intersectionRatio: 0.8,
          top: -40,
        },
        {
          id: ACCOUNT_SECTION.mcp,
          intersectionRatio: 0.1,
          top: 200,
        },
      ]),
    ).toBe(ACCOUNT_SECTION.tokens);
  });

  it("picks the nearest section below the root when none have crossed", () => {
    expect(
      activeAccountSection([
        {
          id: ACCOUNT_SECTION.profile,
          intersectionRatio: 0.4,
          top: 80,
        },
        {
          id: ACCOUNT_SECTION.tokens,
          intersectionRatio: 0.1,
          top: 500,
        },
      ]),
    ).toBe(ACCOUNT_SECTION.profile);
  });

  it("stays on the last section that crossed when none still intersect", () => {
    expect(
      activeAccountSection([
        {
          id: ACCOUNT_SECTION.profile,
          intersectionRatio: 0,
          top: -80,
        },
        {
          id: ACCOUNT_SECTION.mcp,
          intersectionRatio: 0,
          top: 400,
        },
      ]),
    ).toBe(ACCOUNT_SECTION.profile);
  });
});

describe("observationFromEntry", () => {
  it("reads id and top relative to the scroll root", () => {
    const target = document.createElement("div");
    target.id = ACCOUNT_SECTION.profile;
    expect(
      observationFromEntry({
        target,
        intersectionRatio: 0.5,
        boundingClientRect: { top: 120 } as DOMRectReadOnly,
        rootBounds: { top: 40 } as DOMRectReadOnly,
      } as IntersectionObserverEntry),
    ).toEqual({
      id: ACCOUNT_SECTION.profile,
      intersectionRatio: 0.5,
      top: 80,
    });
  });

  it("skips targets without an id", () => {
    expect(
      observationFromEntry({
        target: document.createElement("div"),
        intersectionRatio: 1,
        boundingClientRect: { top: 0 } as DOMRectReadOnly,
        rootBounds: { top: 0 } as DOMRectReadOnly,
      } as IntersectionObserverEntry),
    ).toBeNull();
  });
});
