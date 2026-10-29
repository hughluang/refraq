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

describe("PasswordInput", () => {
  afterEach(() => {
    cleanup();
  });

  it("names the visibility control from the Chinese catalog", async () => {
    stubDomApis();
    const { PasswordInput } = await import("@/components/form/PasswordInput");
    render(
      createElement(
        MantineProvider,
        { env: "test" },
        createElement(PasswordInput, { label: "Password" }),
      ),
    );
    const name = zh["auth.password.visibility"];
    expect(name).toBeTruthy();
    expect(name).not.toBe("auth.password.visibility");
    expect(screen.getByRole("button", { name }).textContent).not.toBe("Toggle password visibility");
    expect(screen.getByRole("button", { name }).getAttribute("aria-label")).toBe(name);
  });
});
