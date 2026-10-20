/** @vitest-environment jsdom */

import { cleanup, render } from "@testing-library/react";
import { createElement } from "react";
import { renderToString } from "react-dom/server";
import { afterEach, describe, expect, it, vi } from "vitest";

import { MantineColorSchemeScript } from "@/components/MantineColorSchemeScript";

describe("MantineColorSchemeScript", () => {
  afterEach(() => {
    cleanup();
  });

  it("emits the blocking color-scheme script from the server render", () => {
    const html = renderToString(createElement(MantineColorSchemeScript));
    expect(html).toContain("data-mantine-script");
    expect(html).toContain("mantine-color-scheme-value");
    expect(html).toContain(': "auto"');
  });

  it("does not create a script element on the client", () => {
    const error = vi.spyOn(console, "error").mockImplementation(() => {});
    render(createElement(MantineColorSchemeScript));
    expect(document.querySelector("script[data-mantine-script]")).toBeNull();
    expect(error.mock.calls.join("\n")).not.toContain("Encountered a script tag");
    error.mockRestore();
  });
});
