/** @vitest-environment jsdom */

import { MantineProvider } from "@mantine/core";
import { cleanup, render, screen } from "@testing-library/react";
import { createElement } from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

function stubDomApis() {
  Object.defineProperty(window, "matchMedia", {
    writable: true,
    value: (query: string) => ({
      matches: false,
      media: query,
      addEventListener: vi.fn(),
      removeEventListener: vi.fn(),
    }),
  });
  class ResizeObserverStub {
    observe() {}
    unobserve() {}
    disconnect() {}
  }
  globalThis.ResizeObserver = ResizeObserverStub;
}

describe("TagNameBadge", () => {
  beforeEach(() => {
    stubDomApis();
  });

  afterEach(() => {
    cleanup();
  });

  it("paints the stored display name without uppercasing", async () => {
    const { TagNameBadge } = await import("@/features/tags/TagNameBadge");
    render(
      createElement(
        MantineProvider,
        null,
        createElement(
          "div",
          null,
          createElement(TagNameBadge, { name: "Straße" }),
          createElement(TagNameBadge, { name: "STRASSE" }),
        ),
      ),
    );

    const sharp = screen.getByText("Straße");
    const ascii = screen.getByText("STRASSE");
    expect(sharp.textContent).toBe("Straße");
    expect(ascii.textContent).toBe("STRASSE");
    expect(sharp.textContent).not.toBe(ascii.textContent);
    expect(sharp.closest(".mantine-Badge-root")).toHaveProperty("style.textTransform", "none");
    expect(ascii.closest(".mantine-Badge-root")).toHaveProperty("style.textTransform", "none");
  });
});
