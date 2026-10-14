/** @vitest-environment jsdom */

import { MantineProvider } from "@mantine/core";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
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
  if (document.fonts == null) {
    Object.defineProperty(document, "fonts", {
      configurable: true,
      value: { addEventListener() {}, removeEventListener() {} },
    });
  }
}

function mount(node: ReturnType<typeof createElement>) {
  return render(createElement(MantineProvider, { env: "test" }, node));
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

  it("keeps a description and an error out of the field flow", async () => {
    const { TextField } = await import("@/components/form/TextField");
    mount(
      createElement(TextField, {
        editable: true,
        label: "Name",
        description: "Help text",
        error: "Required",
        value: "",
        onChange: () => {},
      }),
    );
    const field = screen.getByRole("textbox", { name: "Name" }).closest(".field-chrome");
    expect(field?.querySelector(".mantine-InputWrapper-description")).toBeNull();
    expect(field?.querySelector(".mantine-InputWrapper-error")).toBeNull();
    expect(screen.getByRole("textbox", { name: "Name" }).getAttribute("aria-invalid")).toBe("true");
    expect(screen.getByText("Required")).toBeTruthy();
    expect(screen.queryByText("Help text")).toBeNull();
    fireEvent.click(screen.getByRole("button", { name: "Name form.field.description" }));
    expect(screen.getByText("Help text")).toBeTruthy();
  });

  it("closes an announced error once the value changes", async () => {
    const { TextField } = await import("@/components/form/TextField");
    const props = {
      editable: true,
      label: "Name",
      error: "Required",
      onChange: () => {},
    };
    const view = mount(createElement(TextField, { ...props, value: "" }));
    expect(screen.getByText("Required")).toBeTruthy();
    view.rerender(
      createElement(MantineProvider, { env: "test" }, createElement(TextField, { ...props, value: "a" })),
    );
    expect(screen.queryByText("Required")).toBeNull();
    expect(screen.getByRole("button", { name: "Name form.field.status" })).toBeTruthy();
  });

  it("puts an unlabeled error on the control instead of a new line", async () => {
    const { TextField } = await import("@/components/form/TextField");
    mount(
      createElement(TextField, {
        editable: true,
        "aria-label": "Name",
        error: "Required",
        value: "",
        onChange: () => {},
      }),
    );
    const mark = screen.getByRole("button", { name: "form.field.status" });
    expect(mark.closest(".field-chrome__overlay")).toBeTruthy();
    expect(screen.getByRole("textbox", { name: "Name" }).getAttribute("aria-invalid")).toBe("true");
  });

  it("leaves a bare field unmarked", async () => {
    const { TextField } = await import("@/components/form/TextField");
    mount(
      createElement(TextField, {
        editable: true,
        bare: true,
        "aria-label": "Name",
        description: "Help text",
        error: "Required",
        value: "",
        onChange: () => {},
      }),
    );
    expect(screen.queryByRole("button", { name: /form\.field/ })).toBeNull();
    expect(screen.queryByText("Help text")).toBeNull();
    expect(screen.queryByText("Required")).toBeNull();
    expect(screen.getByRole("textbox", { name: "Name" }).getAttribute("aria-invalid")).not.toBe(
      "true",
    );
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

  it("uses the builder for a daily cron and the raw field when it cannot", async () => {
    const { CronField } = await import("@/components/form/CronField");
    mount(
      createElement(CronField, {
        label: "Cron",
        value: "0 2 * * *",
        onChange: () => {},
      }),
    );
    expect((screen.getByRole("switch") as HTMLInputElement).checked).toBe(false);
    expect(screen.queryByDisplayValue("0 2 * * *")).toBeNull();

    cleanup();
    mount(
      createElement(CronField, {
        label: "Cron",
        value: "0 2 1 * 1",
        onChange: () => {},
      }),
    );
    expect((screen.getByRole("switch") as HTMLInputElement).checked).toBe(true);
    expect(screen.getByRole("textbox").getAttribute("value")).toBe("0 2 1 * 1");
  });

  it("shows formatted JSON in display mode and parses it when editable", async () => {
    const { JsonField } = await import("@/components/form/JsonField");
    const onChange = vi.fn();
    mount(
      createElement(JsonField, {
        editable: false,
        label: "Output",
        value: { status: "ready" },
        onChange,
      }),
    );
    expect(screen.queryByRole("textbox")).toBeNull();
    expect(screen.getByText(/"status": "ready"/)).toBeTruthy();

    cleanup();
    mount(
      createElement(JsonField, {
        editable: true,
        label: "Output",
        value: {},
        onChange,
      }),
    );
    const box = screen.getByRole("textbox", { name: "Output" }) as HTMLTextAreaElement;
    expect(box.value).toBe("{}");
    fireEvent.change(box, { target: { value: '{"status":"ready"}' } });
    fireEvent.blur(box);
    expect(onChange).toHaveBeenCalledWith({ status: "ready" });
  });

  it("keeps invalid JSON in the draft and explains the format", async () => {
    const { JsonField } = await import("@/components/form/JsonField");
    const onChange = vi.fn();
    mount(
      createElement(JsonField, {
        editable: true,
        label: "Output",
        value: { status: "ready" },
        onChange,
        accept: (value) => value !== null && typeof value === "object" && !Array.isArray(value),
        invalidMessage: "Enter a JSON object, for example {\"status\": \"ready\"}.",
      }),
    );
    const box = screen.getByRole("textbox", { name: "Output" });
    fireEvent.change(box, { target: { value: "[1]" } });
    fireEvent.blur(box);
    expect(onChange).not.toHaveBeenCalled();
    expect(box.getAttribute("aria-invalid")).toBe("true");
    await waitFor(() => {
      expect(
        screen.getByText("Enter a JSON object, for example {\"status\": \"ready\"}."),
      ).toBeTruthy();
    });
  });
});
