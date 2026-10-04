/** @vitest-environment jsdom */

import { MantineProvider } from "@mantine/core";
import { cleanup, render, screen } from "@testing-library/react";
import { createElement } from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("@refinedev/core", () => ({
  useTranslate: () => (key: string, options?: Record<string, string | number>) =>
    options ? `${key}:${JSON.stringify(options)}` : key,
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

function mount(node: ReturnType<typeof createElement>) {
  return render(createElement(MantineProvider, null, node));
}

describe("form fields", () => {
  beforeEach(() => {
    stubDomApis();
  });

  afterEach(() => {
    cleanup();
  });

  it("hides the textbox in display mode and shows it when editable", async () => {
    const { TextField } = await import("@/components/form/TextField");
    mount(
      createElement(TextField, {
        editable: false,
        label: "Name",
        required: true,
        value: "Material",
      }),
    );
    expect(screen.queryByRole("textbox")).toBeNull();
    expect(screen.getByText("Material")).toBeTruthy();
    expect(screen.queryByText("*")).toBeNull();

    cleanup();
    mount(
      createElement(TextField, {
        editable: true,
        label: "Name",
        value: "Material",
        onChange: () => {},
      }),
    );
    const box = screen.getByRole("textbox");
    expect(box).toBeTruthy();
    expect(box.hasAttribute("disabled")).toBe(false);
    expect(box.hasAttribute("readonly")).toBe(false);
  });

  it("shows the select option label and no combobox in display mode", async () => {
    const { SelectField } = await import("@/components/form/SelectField");
    mount(
      createElement(SelectField, {
        editable: false,
        label: "Kind",
        data: [{ value: "inner", label: "Inner join" }],
        value: "inner",
      }),
    );
    expect(screen.queryByRole("combobox")).toBeNull();
    expect(screen.getByText("Inner join")).toBeTruthy();
    expect(screen.queryByText("inner")).toBeNull();
  });

  it("shows the unmatched select value as itself", async () => {
    const { SelectField } = await import("@/components/form/SelectField");
    mount(
      createElement(SelectField, {
        editable: false,
        label: "Kind",
        data: [{ value: "inner", label: "Inner join" }],
        value: "mystery",
      }),
    );
    expect(screen.getByText("mystery")).toBeTruthy();
  });

  it("shows locale yes/no for a switch and no switch control", async () => {
    const { SwitchField } = await import("@/components/form/SwitchField");
    mount(
      createElement(SwitchField, {
        editable: false,
        label: "Enabled",
        checked: true,
      }),
    );
    expect(screen.queryByRole("switch")).toBeNull();
    expect(screen.getByText("form.value.yes")).toBeTruthy();
  });

  it("shows a cron sentence beside the expression", async () => {
    const { CronField } = await import("@/components/form/CronField");
    mount(
      createElement(CronField, {
        editable: false,
        label: "Cron",
        value: "0 2 * * *",
        zone: "UTC",
      }),
    );
    expect(screen.queryByRole("textbox")).toBeNull();
    expect(screen.getByText(/form\.cron\.daily/)).toBeTruthy();
    expect(screen.getByText(/0 2 \* \* \*/)).toBeTruthy();
  });
});
