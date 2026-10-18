/** @vitest-environment jsdom */

import { MantineProvider } from "@mantine/core";
import { cleanup, render, screen } from "@testing-library/react";
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
}

describe("StatusBadge", () => {
  beforeEach(() => {
    stubDomApis();
  });

  afterEach(() => {
    cleanup();
  });

  it("shows the translated label for the tone", async () => {
    const { StatusBadge } = await import("@/components/display/StatusBadge");
    render(
      createElement(
        MantineProvider,
        null,
        createElement(StatusBadge, {
          tone: "running",
          labelKey: "status.job.running",
        }),
      ),
    );

    expect(screen.getByText("status.job.running")).toBeTruthy();
    expect(screen.queryByText("running")).toBeNull();
  });
});
