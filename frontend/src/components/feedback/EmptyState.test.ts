/** @vitest-environment jsdom */

import { MantineProvider } from "@mantine/core";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { createElement, type ReactNode } from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { EmptyState } from "@/components/feedback/EmptyState";

vi.mock("@refinedev/core", () => ({
  useTranslate: () => (key: string) => key,
}));

function shell(node: ReactNode) {
  return createElement(MantineProvider, { env: "test" }, node);
}

describe("EmptyState", () => {
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

  it("shows an icon, a next step, and an optional action", () => {
    render(
      shell(
        createElement(EmptyState, {
          message: "Create a record to start.",
          action: createElement("button", { type: "button" }, "Create"),
        }),
      ),
    );
    expect(screen.getByText("Create a record to start.")).toBeTruthy();
    expect(screen.getByRole("button", { name: "Create" })).toBeTruthy();
    expect(document.querySelector("svg")).toBeTruthy();
  });
});
