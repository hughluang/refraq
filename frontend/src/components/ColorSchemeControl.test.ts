/** @vitest-environment jsdom */

import { readFileSync } from "node:fs";
import path from "node:path";

import { MantineProvider } from "@mantine/core";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { act, createElement } from "react";
import { hydrateRoot } from "react-dom/client";
import { renderToString } from "react-dom/server";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { COLOR_SCHEME_PREFERENCE_ATTRIBUTE } from "@/components/MantineColorSchemeScript";

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

function optionText(trigger: HTMLElement, scheme: string) {
  return [...trigger.querySelectorAll(`[data-color-scheme-option="${scheme}"]`)]
    .map((node) => node.textContent)
    .join("");
}

describe("ColorSchemeControl", () => {
  beforeEach(() => {
    stubDomApis();
    window.localStorage.clear();
    document.documentElement.removeAttribute(COLOR_SCHEME_PREFERENCE_ATTRIBUTE);
    document.documentElement.removeAttribute("data-mantine-color-scheme");
  });

  afterEach(() => {
    cleanup();
  });

  it("shows the stored preference while the resolved scheme stays light", async () => {
    window.localStorage.setItem("mantine-color-scheme-value", "auto");
    const { ColorSchemeControl } = await import("@/components/ColorSchemeControl");
    render(
      createElement(
        MantineProvider,
        { defaultColorScheme: "auto", env: "test" },
        createElement(ColorSchemeControl),
      ),
    );

    const trigger = screen.getByRole("button", { name: "colorScheme.label" });
    expect(optionText(trigger, "light")).toBe("colorScheme.light");
    expect(optionText(trigger, "dark")).toBe("colorScheme.dark");
    expect(optionText(trigger, "auto")).toBe("colorScheme.system");
    expect(document.documentElement.getAttribute(COLOR_SCHEME_PREFERENCE_ATTRIBUTE)).toBe(
      "auto",
    );
    expect(document.documentElement.getAttribute("data-mantine-color-scheme")).toBe("light");

    const css = readFileSync(
      path.resolve("src/components/ColorSchemeControl.css"),
      "utf8",
    );
    expect(css).toContain(`html[${COLOR_SCHEME_PREFERENCE_ATTRIBUTE}="auto"]`);
    expect(css).toContain(`html:not([${COLOR_SCHEME_PREFERENCE_ATTRIBUTE}])`);

    fireEvent.click(trigger);
    expect(
      screen.getByRole("menuitemradio", { name: "colorScheme.system" }).getAttribute("aria-checked"),
    ).toBe("true");
    fireEvent.click(screen.getByRole("menuitemradio", { name: "colorScheme.dark" }));

    expect(window.localStorage.getItem("mantine-color-scheme-value")).toBe("dark");
    expect(document.documentElement.getAttribute(COLOR_SCHEME_PREFERENCE_ATTRIBUTE)).toBe(
      "dark",
    );
    expect(document.documentElement.getAttribute("data-mantine-color-scheme")).toBe("dark");
  });

  it("keeps the resolved light scheme when the choice is system", async () => {
    window.localStorage.setItem("mantine-color-scheme-value", "light");
    const { ColorSchemeControl } = await import("@/components/ColorSchemeControl");
    render(
      createElement(
        MantineProvider,
        { defaultColorScheme: "auto", env: "test" },
        createElement(ColorSchemeControl),
      ),
    );

    fireEvent.click(screen.getByRole("button", { name: "colorScheme.label" }));
    fireEvent.click(screen.getByRole("menuitemradio", { name: "colorScheme.system" }));

    expect(window.localStorage.getItem("mantine-color-scheme-value")).toBe("auto");
    expect(document.documentElement.getAttribute(COLOR_SCHEME_PREFERENCE_ATTRIBUTE)).toBe(
      "auto",
    );
    expect(document.documentElement.getAttribute("data-mantine-color-scheme")).toBe("light");
  });

  it("server markup includes every preference when storage already has a choice", async () => {
    window.localStorage.setItem("mantine-color-scheme-value", "dark");
    const { ColorSchemeControl } = await import("@/components/ColorSchemeControl");
    const element = createElement(
      MantineProvider,
      { defaultColorScheme: "auto", env: "test" },
      createElement(ColorSchemeControl),
    );

    const html = renderToString(element);
    expect(html).toContain('data-color-scheme-option="light"');
    expect(html).toContain('data-color-scheme-option="dark"');
    expect(html).toContain('data-color-scheme-option="auto"');
    expect(html).toContain("colorScheme.light");
    expect(html).toContain("colorScheme.dark");
    expect(html).toContain("colorScheme.system");
    expect(html).toContain("tabler-icon-sun");
    expect(html).toContain("tabler-icon-moon");
    expect(html).toContain("tabler-icon-device-desktop");

    const container = document.createElement("div");
    document.body.appendChild(container);
    container.innerHTML = html;
    const error = vi.spyOn(console, "error").mockImplementation(() => {});
    const root = await act(async () => hydrateRoot(container, element));
    expect(error.mock.calls.join("\n")).not.toContain("Hydration");

    root.unmount();
    error.mockRestore();
  });
});
