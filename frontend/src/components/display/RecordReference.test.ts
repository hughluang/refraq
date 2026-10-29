/** @vitest-environment jsdom */

import { MantineProvider } from "@mantine/core";
import { cleanup, render, screen } from "@testing-library/react";
import { createElement } from "react";
import { afterEach, describe, expect, it, vi } from "vitest";

import zh from "@/locales/zh-CN/common.json";

vi.mock("@refinedev/core", () => ({
  useTranslate: () => (key: string, values?: Record<string, unknown>) => {
    const template = (zh as Record<string, string>)[key] ?? key;
    if (!values) return template;
    return template.replace(/\{\{(\w+)\}\}/g, (_, name: string) => String(values[name] ?? ""));
  },
  useNotification: () => ({ open: vi.fn() }),
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

describe("RecordReference", () => {
  afterEach(() => {
    cleanup();
  });

  it("names the copy control with the catalog sentence for that identifier", async () => {
    stubDomApis();
    const { RecordReference } = await import("@/components/display/RecordReference");
    render(
      createElement(
        MantineProvider,
        { env: "test" },
        createElement(RecordReference, { name: "Office", recordKey: "hac_81e883a9d4bb" }),
      ),
    );
    const expected = String(zh["recordReference.copy"]).replace("{{value}}", "hac_81e883a9d4bb");
    const button = screen.getByRole("button", { name: expected });
    expect(button.getAttribute("aria-label")).toBe(expected);
    expect(button.getAttribute("aria-label")).not.toBe("recordReference.copy");
  });
});
