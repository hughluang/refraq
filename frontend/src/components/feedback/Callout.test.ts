/** @vitest-environment jsdom */

import { MantineProvider } from "@mantine/core";
import { cleanup, render, screen } from "@testing-library/react";
import { createElement, type ReactNode } from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { Callout } from "@/components/feedback/Callout";

function shell(node: ReactNode) {
  return createElement(MantineProvider, { env: "test" }, node);
}

describe("Callout", () => {
  beforeEach(() => {
    Object.defineProperty(window, "matchMedia", {
      writable: true,
      value: (query: string) => ({
        matches: false,
        media: query,
        addEventListener: vi.fn(),
        removeEventListener: vi.fn(),
      }),
    });
  });

  afterEach(() => {
    cleanup();
  });

  it("shows fixed copy without a close control or an alert announcement", () => {
    render(
      shell(
        createElement(
          Callout,
          { tone: "info", title: "Hidden columns" },
          "Physical columns stay hidden.",
        ),
      ),
    );

    expect(screen.getByText("Hidden columns")).toBeTruthy();
    expect(screen.getByText("Physical columns stay hidden.")).toBeTruthy();
    expect(screen.queryByRole("alert")).toBeNull();
    expect(screen.queryByRole("button")).toBeNull();
  });

  it("paints info and notice with different theme tokens and neither is red", () => {
    render(
      shell(
        createElement(
          "div",
          null,
          createElement(
            Callout,
            { tone: "info", title: "Hidden columns" },
            "Physical columns stay hidden.",
          ),
          createElement(Callout, { tone: "notice" }, "This purpose stays closed."),
        ),
      ),
    );

    expect(screen.getByText("This purpose stays closed.")).toBeTruthy();
    expect(screen.queryByRole("alert")).toBeNull();
    expect(screen.queryByRole("button")).toBeNull();

    const infoStyle = paintedStyle("Physical columns stay hidden.");
    const noticeStyle = paintedStyle("This purpose stays closed.");
    expect(infoStyle).toContain("var(--refraq-tone-info)");
    expect(noticeStyle).toContain("var(--refraq-tone-warning)");
    expect(infoStyle).not.toContain("--refraq-tone-danger");
    expect(noticeStyle).not.toContain("--refraq-tone-danger");
    expect(infoStyle).not.toMatch(/red/i);
    expect(noticeStyle).not.toMatch(/red/i);
    expect(infoStyle).not.toBe(noticeStyle);
  });
});

function paintedStyle(text: string): string {
  let node: HTMLElement | null = screen.getByText(text);
  while (node) {
    const style = node.getAttribute("style") ?? "";
    if (style.includes("--alert-") || style.includes("--refraq-tone-")) return style;
    node = node.parentElement;
  }
  return "";
}
