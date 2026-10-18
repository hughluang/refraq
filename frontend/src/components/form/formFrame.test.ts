/** @vitest-environment jsdom */

import { MantineProvider } from "@mantine/core";
import { act, cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { createElement, useState, type ReactNode } from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { ApiError } from "@/lib/api";

const copy = vi.hoisted(() => ({
  text: vi.fn(async (_value: string) => {}),
}));

const gate = {
  n: 0,
  release: null as (() => void) | null,
};

vi.mock("@refinedev/core", () => ({
  useTranslate: () => (key: string) =>
    (
      {
        "layout.leave.title": "Discard unsaved changes?",
        "layout.leave.stay": "Stay",
        "layout.leave.discard": "Discard",
      } as Record<string, string>
    )[key] ?? key,
}));

vi.mock("next/navigation", () => ({
  usePathname: () => "/console/sources",
  useRouter: () => ({ push: vi.fn(), replace: vi.fn(), refresh: vi.fn() }),
  useSearchParams: () => new URLSearchParams(),
}));

vi.mock("@/lib/copy-text", () => ({
  copyText: (value: string) => copy.text(value),
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

function shell(node: ReactNode) {
  return createElement(MantineProvider, { env: "test" }, node);
}

describe("form frame", () => {
  beforeEach(() => {
    stubDomApis();
    copy.text.mockClear();
    gate.n = 0;
    gate.release = null;
  });

  afterEach(async () => {
    cleanup();
    const guard = await import("@/components/navigation/leaveGuard");
    if (guard.leavePromptOpen()) guard.settleLeavePrompt(false);
    guard.releaseLeaveGuardSuppression();
  });

  it("registers dirty state and clears it when the snapshot is replaced", async () => {
    const { useConsoleForm } = await import("@/components/form/useConsoleForm");
    const { hasDirtyRegistration } = await import("@/components/navigation/leaveGuard");

    function Probe() {
      const form = useConsoleForm({ initialValues: { name: "Ada" } });
      return createElement(
        "div",
        null,
        createElement("input", {
          "aria-label": "Name",
          ...form.fieldProps("name"),
        }),
        createElement(
          "button",
          { type: "button", onClick: () => form.markSaved() },
          "Mark saved",
        ),
        createElement(
          "button",
          { type: "button", onClick: () => form.resetDirty() },
          "Reset dirty",
        ),
        createElement("span", null, form.dirty ? "dirty" : "clean"),
      );
    }

    render(shell(createElement(Probe)));
    expect(screen.getByText("clean")).toBeTruthy();
    expect(hasDirtyRegistration()).toBe(false);

    fireEvent.change(screen.getByRole("textbox", { name: "Name" }), {
      target: { value: "Bea" },
    });
    expect(screen.getByText("dirty")).toBeTruthy();
    await waitFor(() => {
      expect(hasDirtyRegistration()).toBe(true);
    });

    fireEvent.click(screen.getByRole("button", { name: "Mark saved" }));
    expect(screen.getByText("clean")).toBeTruthy();
    await waitFor(() => {
      expect(hasDirtyRegistration()).toBe(false);
    });

    fireEvent.change(screen.getByRole("textbox", { name: "Name" }), {
      target: { value: "Cy" },
    });
    expect(screen.getByText("dirty")).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "Reset dirty" }));
    expect(screen.getByText("clean")).toBeTruthy();
  });

  it("maps 422 details onto fields, focuses the first, and keeps the rest unmapped", async () => {
    const { useConsoleForm } = await import("@/components/form/useConsoleForm");
    const { FormErrorSummary } = await import("@/components/form/FormErrorSummary");

    function Probe() {
      const form = useConsoleForm({
        initialValues: { account: "", host: "", name: "" },
      });
      const [unmapped, setUnmapped] = useState<
        { field?: string; message?: string; code?: string }[]
      >([]);
      const [failure, setFailure] = useState("");
      return createElement(
        "div",
        null,
        createElement(FormErrorSummary, {
          message: "Could not save this form.",
          detail: "Request validation failed",
          requestId: "rid-1",
          unmapped,
        }),
        createElement("input", { "aria-label": "Account", ...form.getInputProps("account") }),
        createElement("input", { "aria-label": "Host", ...form.getInputProps("host") }),
        createElement("input", { "aria-label": "Name", ...form.getInputProps("name") }),
        createElement("pre", { "data-testid": "errors" }, JSON.stringify(form.errors)),
        createElement("span", { "data-testid": "failure" }, failure),
        createElement(
          "button",
          {
            type: "button",
            onClick: () => {
              const result = form.applyApiError(
                new ApiError(
                  422,
                  "REQUEST_INVALID",
                  "Request validation failed",
                  "rid-1",
                  {},
                  [
                    { field: "account", code: "VALUE_MISSING", message: "Field required" },
                    { field: "access.host", code: "VALUE_INVALID", message: "Bad host" },
                    { field: "name", code: "VALUE_INVALID", message: "Bad name" },
                    { field: "missing", code: "VALUE_INVALID", message: "Nope" },
                  ],
                ),
                { "access.host": "host", name: "host" },
              );
              setUnmapped(result.unmapped);
            },
          },
          "Apply",
        ),
        createElement(
          "button",
          {
            type: "button",
            onClick: () => {
              const result = form.applyApiError(
                new ApiError(500, "INTERNAL_ERROR", "Something broke", "rid-500"),
              );
              setFailure(`${result.mapped.length}/${result.unmapped.length}`);
            },
          },
          "Apply failure",
        ),
      );
    }

    render(shell(createElement(Probe)));
    fireEvent.click(screen.getByRole("button", { name: "Apply" }));

    await waitFor(() => {
      expect(document.activeElement).toBe(screen.getByRole("textbox", { name: "Account" }));
    });
    const errors = screen.getByTestId("errors").textContent ?? "";
    expect(errors).toContain('"account":"Field required"');
    expect(errors).toContain('"host":"Bad host"');
    expect(errors).toContain('"name":"Bad name"');
    expect(errors).not.toContain("Nope");
    const alert = screen.getByRole("alert");
    expect(alert.textContent).toContain("Could not save this form.");
    const disclosure = alert.querySelector("details");
    expect(disclosure?.textContent).toContain("Request validation failed");
    expect(disclosure?.textContent).toContain("rid-1");
    expect(disclosure?.textContent).toContain("missing: Nope");
    expect(alert.querySelector("summary")?.textContent).toBe("form.error.details");

    fireEvent.click(screen.getByRole("button", { name: "Apply failure" }));
    expect(screen.getByTestId("failure").textContent).toBe("0/0");
    expect(screen.getByTestId("errors").textContent).toContain("Field required");
  });

  it("copies the server detail, request id, and unmapped lines", async () => {
    const { FormErrorSummary } = await import("@/components/form/FormErrorSummary");
    render(
      shell(
        createElement(FormErrorSummary, {
          message: "Could not save this form.",
          detail: "Request validation failed",
          requestId: "rid-9",
          unmapped: [{ field: "missing", message: "Nope" }],
        }),
      ),
    );
    fireEvent.click(screen.getByRole("button", { name: "form.error.copy" }));
    await waitFor(() => {
      expect(copy.text).toHaveBeenCalledWith(
        "Request validation failed\ncommon.requestId: rid-9\nmissing: Nope",
      );
    });
  });

  it("validates on blur for a touched field and again on change after an error", async () => {
    const { useConsoleForm } = await import("@/components/form/useConsoleForm");

    function Probe() {
      const form = useConsoleForm({
        initialValues: { name: "" },
        validate: {
          name: (value) => (value.trim() ? null : "Required"),
        },
      });
      const props = form.getInputProps("name");
      return createElement(
        "form",
        { onSubmit: form.onSubmit(() => {}) },
        createElement("input", {
          "aria-label": "Name",
          value: props.value,
          onChange: props.onChange,
          onBlur: props.onBlur,
          onFocus: props.onFocus,
          "data-path": props["data-path"],
        }),
        props.error ? createElement("span", null, String(props.error)) : null,
        createElement("button", { type: "submit" }, "Save"),
      );
    }

    render(shell(createElement(Probe)));
    const input = screen.getByRole("textbox", { name: "Name" });
    fireEvent.blur(input);
    expect(screen.queryByText("Required")).toBeNull();

    fireEvent.focus(input);
    fireEvent.blur(input);
    expect(screen.getByText("Required")).toBeTruthy();

    fireEvent.change(input, { target: { value: "A" } });
    expect(screen.queryByText("Required")).toBeNull();

    fireEvent.change(input, { target: { value: " " } });
    expect(screen.queryByText("Required")).toBeNull();
    fireEvent.blur(input);
    expect(screen.getByText("Required")).toBeTruthy();

    fireEvent.change(input, { target: { value: "A" } });
    fireEvent.change(input, { target: { value: "" } });
    fireEvent.click(screen.getByRole("button", { name: "Save" }));
    expect(screen.getByText("Required")).toBeTruthy();
    expect(document.activeElement).toBe(input);
  });

  it("blocks a second submit while the first is still running", async () => {
    const { useConsoleForm } = await import("@/components/form/useConsoleForm");

    function Probe() {
      const form = useConsoleForm({ initialValues: { name: "Ada" } });
      const send = form.onSubmit(async () => {
        gate.n += 1;
        await new Promise<void>((resolve) => {
          gate.release = resolve;
        });
      });
      return createElement(
        "div",
        null,
        createElement(
          "button",
          {
            type: "button",
            onClick: () => {
              send();
              send();
            },
          },
          "Send",
        ),
        createElement("span", null, form.submitting ? "loading" : "idle"),
      );
    }

    render(shell(createElement(Probe)));
    fireEvent.click(screen.getByRole("button", { name: "Send" }));
    expect(gate.n).toBe(1);
    expect(screen.getByText("loading")).toBeTruthy();

    fireEvent.click(screen.getByRole("button", { name: "Send" }));
    expect(gate.n).toBe(1);

    gate.release?.();
    await waitFor(() => {
      expect(screen.getByText("idle")).toBeTruthy();
    });
  });

  it("asks before discarding a dirty dialog and ignores the overlay", async () => {
    const { FormDialog } = await import("@/components/form/FormDialog");
    const { LeaveGuardProvider } = await import("@/components/navigation/leaveGuard");
    const onClose = vi.fn();
    const onSubmit = vi.fn();

    function Probe({ dirty }: { dirty: boolean }) {
      return createElement(
        LeaveGuardProvider,
        null,
        createElement(
          FormDialog,
          {
            opened: true,
            dirty,
            onClose,
            onSubmit,
            title: "Create source",
            submitLabel: "sources.create",
          },
          createElement("input", { "aria-label": "Name" }),
          createElement("input", { "aria-label": "Host" }),
        ),
      );
    }

    render(shell(createElement(Probe, { dirty: true })));
    await waitFor(() => {
      expect(document.activeElement).toBe(screen.getByRole("textbox", { name: "Name" }));
    });

    act(() => {
      document.body.dispatchEvent(
        new KeyboardEvent("keydown", { key: "Escape", bubbles: true, cancelable: true }),
      );
    });
    expect(await screen.findByText("Discard unsaved changes?")).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "Stay" }));
    await waitFor(() => {
      expect(screen.queryByText("Discard unsaved changes?")).toBeNull();
    });
    expect(onClose).not.toHaveBeenCalled();

    fireEvent.click(document.querySelector(".form-dialog-overlay") as Element);
    expect(onClose).not.toHaveBeenCalled();
    expect(screen.queryByText("Discard unsaved changes?")).toBeNull();

    fireEvent.click(screen.getByRole("button", { name: "form.dialog.close" }));
    fireEvent.click(await screen.findByRole("button", { name: "Stay" }));
    expect(onClose).not.toHaveBeenCalled();

    fireEvent.click(screen.getByRole("button", { name: "common.cancel" }));
    fireEvent.click(await screen.findByRole("button", { name: "Discard" }));
    await waitFor(() => {
      expect(onClose).toHaveBeenCalledTimes(1);
    });

    fireEvent.submit(document.querySelector("form") as HTMLFormElement);
    expect(onSubmit).toHaveBeenCalledTimes(1);
    fireEvent.keyDown(screen.getByRole("textbox", { name: "Name" }), { key: "Enter" });
    expect(onSubmit).toHaveBeenCalledTimes(2);
    const cancel = screen.getByRole("button", { name: "common.cancel" });
    const submit = screen.getByRole("button", { name: "sources.create" });
    expect(cancel.compareDocumentPosition(submit) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
  });

  it("closes from the overlay when the dialog is clean", async () => {
    const { FormDialog } = await import("@/components/form/FormDialog");
    const onClose = vi.fn();
    render(
      shell(
        createElement(
          FormDialog,
          {
            opened: true,
            dirty: false,
            onClose,
            onSubmit: () => {},
            title: "Create source",
            submitLabel: "sources.create",
          },
          createElement("input", { "aria-label": "Name" }),
        ),
      ),
    );
    fireEvent.click(document.querySelector(".form-dialog-overlay") as Element);
    expect(onClose).toHaveBeenCalledTimes(1);
    expect(screen.queryByText("Discard unsaved changes?")).toBeNull();
  });

  it("maps a body-prefixed path and an alias of the stripped path", async () => {
    const { useConsoleForm } = await import("@/components/form/useConsoleForm");

    function Probe() {
      const form = useConsoleForm({
        initialValues: { account: "", host: "" },
      });
      return createElement(
        "div",
        null,
        createElement("input", { "aria-label": "Account", ...form.getInputProps("account") }),
        createElement("input", { "aria-label": "Host", ...form.getInputProps("host") }),
        createElement("pre", { "data-testid": "errors" }, JSON.stringify(form.errors)),
        createElement(
          "button",
          {
            type: "button",
            onClick: () => {
              form.applyApiError(
                new ApiError(422, "REQUEST_INVALID", "Request validation failed", "rid", {}, [
                  { field: "body.account", code: "VALUE_MISSING", message: "Field required" },
                  { field: "body.access.host", code: "VALUE_INVALID", message: "Bad host" },
                ]),
                { "access.host": "host" },
              );
            },
          },
          "Apply",
        ),
      );
    }

    render(shell(createElement(Probe)));
    fireEvent.click(screen.getByRole("button", { name: "Apply" }));
    await waitFor(() => {
      expect(document.activeElement).toBe(screen.getByRole("textbox", { name: "Account" }));
    });
    const errors = screen.getByTestId("errors").textContent ?? "";
    expect(errors).toContain('"account":"Field required"');
    expect(errors).toContain('"host":"Bad host"');
  });

  it("localizes the summary and keeps a fully mapped 422 on the fields", async () => {
    const { saveFailureFrom, FormErrorSummary } = await import(
      "@/components/form/FormErrorSummary"
    );
    const translate = (key: string) =>
      (
        {
          "problems.REQUEST_INVALID": "The request is not valid.",
          "problems.unknown": "Something went wrong.",
        } as Record<string, string>
      )[key] ?? key;
    const invalid = new ApiError(
      422,
      "REQUEST_INVALID",
      "Request validation failed",
      "rid-422",
      {},
      [{ field: "missing", message: "Nope" }],
    );
    const unmapped = saveFailureFrom(
      translate,
      invalid,
      { mapped: [], unmapped: invalid.details ?? [] },
      "fallback",
    );
    expect(unmapped?.message).toBe("The request is not valid.");
    expect(unmapped?.detail).toBe("Request validation failed");
    const server = new ApiError(500, "INTERNAL_ERROR", "Internal server error", "rid-500");
    const generic = saveFailureFrom(
      translate,
      server,
      { mapped: [], unmapped: [] },
      "fallback",
    );
    expect(generic?.message).toBe("Something went wrong.");
    expect(generic?.message).not.toBe("Internal server error");
    expect(
      saveFailureFrom(
        translate,
        invalid,
        { mapped: [{ field: "account", message: "Field required" }], unmapped: [] },
        "fallback",
      ),
    ).toBeNull();

    if (!generic) throw new Error("expected a form-level summary");
    render(shell(createElement(FormErrorSummary, { failure: generic })));
    const alert = screen.getByRole("alert");
    const disclosure = alert.querySelector("details");
    const main = (alert.textContent ?? "").replace(disclosure?.textContent ?? "", "");
    expect(main).toContain("Something went wrong.");
    expect(main).not.toContain("Internal server error");
    expect(disclosure?.textContent).toContain("Internal server error");
    expect(disclosure?.textContent).toContain("rid-500");
  });

  it("clears dirty after a successful submit and releases suppression when submit fails", async () => {
    const { useConsoleForm } = await import("@/components/form/useConsoleForm");
    const guard = await import("@/components/navigation/leaveGuard");

    function Probe() {
      const form = useConsoleForm({ initialValues: { name: "Ada" } });
      return createElement(
        "div",
        null,
        createElement("input", { "aria-label": "Name", ...form.fieldProps("name") }),
        createElement(
          "button",
          {
            type: "button",
            onClick: () => {
              void form.submit(async () => {});
            },
          },
          "Save",
        ),
        createElement(
          "button",
          {
            type: "button",
            onClick: () => {
              void form.submit(async () => {
                guard.suppressLeaveGuard();
                throw new Error("nope");
              });
            },
          },
          "Fail",
        ),
        createElement(
          "button",
          {
            type: "button",
            onClick: () => {
              void form.submit(async () => {
                guard.suppressLeaveGuard();
                form.applyApiError(new ApiError(500, "INTERNAL_ERROR", "Internal server error"));
              });
            },
          },
          "Report",
        ),
        createElement("span", null, form.dirty ? "dirty" : "clean"),
      );
    }

    render(shell(createElement(Probe)));
    fireEvent.change(screen.getByRole("textbox", { name: "Name" }), {
      target: { value: "Bea" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Save" }));
    await waitFor(() => {
      expect(screen.getByText("clean")).toBeTruthy();
      expect(guard.hasDirtyRegistration()).toBe(false);
    });

    fireEvent.change(screen.getByRole("textbox", { name: "Name" }), {
      target: { value: "Cy" },
    });
    await waitFor(() => {
      expect(guard.hasDirtyRegistration()).toBe(true);
    });
    fireEvent.click(screen.getByRole("button", { name: "Fail" }));
    await waitFor(() => {
      expect(screen.getByText("dirty")).toBeTruthy();
      expect(guard.isLeaveBlocked()).toBe(true);
    });

    fireEvent.click(screen.getByRole("button", { name: "Report" }));
    await waitFor(() => {
      expect(screen.getByText("dirty")).toBeTruthy();
      expect(guard.isLeaveBlocked()).toBe(true);
    });
  });

  it("groups fields under a section heading that is not the page title", async () => {
    const { FormSection } = await import("@/components/form/FormSection");
    render(
      shell(
        createElement(
          FormSection,
          { title: "Access", description: "How to connect", columns: 2, order: 3 },
          "Host",
        ),
      ),
    );
    const heading = screen.getByRole("heading", { name: "Access" });
    expect(heading.tagName).toBe("H3");
    expect(screen.getByText("How to connect")).toBeTruthy();
    expect(document.querySelector(".form-section__grid")?.getAttribute("data-columns")).toBe("2");
  });

  it("shows persistent helper text without opening the reference popover", async () => {
    const { TextField } = await import("@/components/form/TextField");
    const view = render(
      shell(
        createElement(TextField, {
          editable: true,
          label: "Host",
          description: "Long reference",
          helper: "host:port",
          value: "",
          onChange: () => {},
        }),
      ),
    );
    const helper = screen.getByText("host:port");
    const box = screen.getByRole("textbox", { name: "Host" });
    expect(helper.closest(".field-chrome__helper")).toBeTruthy();
    expect(box.getAttribute("aria-describedby")).toBe(helper.id);
    expect(screen.queryByText("Long reference")).toBeNull();

    view.rerender(
      shell(
        createElement(TextField, {
          editable: true,
          label: "Host",
          description: "Long reference",
          helper: "host:port",
          value: "db",
          onChange: () => {},
        }),
      ),
    );
    expect(screen.getByRole("textbox", { name: "Host" }).getAttribute("aria-describedby")).toBe(
      screen.getByText("host:port").id,
    );
  });
});
