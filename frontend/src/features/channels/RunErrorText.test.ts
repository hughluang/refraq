/** @vitest-environment jsdom */

import { MantineProvider } from "@mantine/core";
import { cleanup, render, screen } from "@testing-library/react";
import { createElement } from "react";
import { afterEach, describe, expect, it, vi } from "vitest";

import zh from "@/locales/zh-CN/common.json";

vi.mock("@refinedev/core", () => ({
  useTranslate: () => (key: string) => (zh as Record<string, string>)[key] ?? key,
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

describe("RunErrorText", () => {
  afterEach(() => {
    cleanup();
  });

  it("keeps the localized sentence and the English occurrence as two sentences", async () => {
    stubDomApis();
    const { RunErrorText } = await import("@/features/channels/RunErrorText");
    render(
      createElement(
        MantineProvider,
        { env: "test" },
        createElement(RunErrorText, {
          code: "CHANNEL_NODE_FAILED",
          message: "Origin is not allowed",
        }),
      ),
    );
    const sentence = String(zh["problems.CHANNEL_NODE_FAILED"]);
    const label = screen.getByText(sentence);
    const detail = screen.getByText("Origin is not allowed");
    expect(label.compareDocumentPosition(detail) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
    expect(label.parentElement?.textContent).toBe(`${sentence}\nOrigin is not allowed`);
    expect(label.parentElement?.textContent).not.toContain(`${sentence}Origin`);
  });
});
