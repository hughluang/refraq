/** @vitest-environment jsdom */

import { MantineProvider } from "@mantine/core";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { createElement } from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("@refinedev/core", () => ({
  useTranslate: () => (key: string) => key,
}));

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

describe("ColorSchemeControl", () => {
  beforeEach(() => {
    stubDomApis();
    window.localStorage.clear();
  });

  afterEach(() => {
    cleanup();
  });

  it("offers light, dark, and system, and stores the choice", async () => {
    const { ColorSchemeControl } = await import("@/components/ColorSchemeControl");
    render(
      createElement(
        MantineProvider,
        { defaultColorScheme: "auto", env: "test" },
        createElement(ColorSchemeControl),
      ),
    );

    const trigger = screen.getByRole("button", { name: "colorScheme.label" });
    expect(trigger.textContent).toContain("colorScheme.system");

    fireEvent.click(trigger);
    fireEvent.click(
      screen.getByRole("menuitem", { name: "colorScheme.dark" }),
    );

    expect(screen.getByRole("button", { name: "colorScheme.label" }).textContent).toContain(
      "colorScheme.dark",
    );
    expect(window.localStorage.getItem("mantine-color-scheme-value")).toBe("dark");
  });
});
