/** @vitest-environment jsdom */

import { cleanup, render, screen } from "@testing-library/react";
import { createElement } from "react";
import { afterEach, describe, expect, it, vi } from "vitest";

vi.mock("@refinedev/core", () => ({
  useTranslate: () => (key: string) => key,
}));

describe("Instant", () => {
  afterEach(() => {
    cleanup();
  });

  it("renders an invalid instant as a local contract error", async () => {
    const { Instant } = await import("@/components/display/Instant");

    expect(() =>
      render(
        createElement(Instant, {
          value: "2026-10-11T06:00:29",
          requestId: "req_01",
        }),
      ),
    ).not.toThrow();
    expect(screen.getByText("problems.API_CONTRACT_INVALID")).toBeTruthy();
    expect(screen.getByText("common.requestId: req_01")).toBeTruthy();

    cleanup();

    expect(() => render(createElement(Instant, { value: "2026-10-11T06:00:29" }))).not.toThrow();
    expect(screen.getByText("problems.API_CONTRACT_INVALID")).toBeTruthy();
    expect(screen.queryByText(/common\.requestId/)).toBeNull();
  });
});
