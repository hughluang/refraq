/** @vitest-environment jsdom */

import { MantineProvider } from "@mantine/core";
import { notifications } from "@mantine/notifications";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { createElement, type ReactNode } from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { FormErrorSummary } from "@/components/form/FormErrorSummary";
import { ApiError } from "@/lib/api";
import { ConsoleNotifications } from "@/providers/notification-provider";

const copy = vi.hoisted(() => ({
  text: vi.fn(async (_value: string) => {}),
}));

vi.mock("@refinedev/core", () => ({
  useTranslate: () => (key: string, options?: Record<string, unknown>) => {
    const dictionary: Record<string, string> = {
      "common.cancel": "Cancel",
      "common.confirm": "Confirm",
      "feedback.confirm.title": "Confirm {{record}}",
      "feedback.confirm.body": "{{record}}: {{consequence}} This cannot be undone.",
      "feedback.success.title": "{{outcome}} — {{record}}",
      "feedback.undo": "Undo",
      "feedback.undo.done": "Undone",
      "problems.unknown": "Something went wrong. Try again.",
      "form.error.details": "Details",
      "form.error.copy": "Copy details",
      "common.requestId": "Request ID",
      "common.copy.success": "Copied",
      "common.copy.failed": "Copy failed",
    };
    const template = dictionary[key] ?? key;
    if (!options) return template;
    return template.replace(/\{\{(\w+)\}\}/g, (_, name: string) =>
      String(options[name] ?? ""),
    );
  },
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
}

function shell(node: ReactNode) {
  return createElement(
    MantineProvider,
    { env: "test" },
    createElement(ConsoleNotifications),
    node,
  );
}

describe("console actions", () => {
  beforeEach(() => {
    stubDomApis();
    copy.text.mockClear();
    notifications.clean();
  });

  afterEach(() => {
    cleanup();
    notifications.clean();
  });

  it("confirm focuses Cancel and names the record", async () => {
    const execute = vi.fn(async () => {});
    const { useConsoleMutation } = await import("@/components/feedback/useConsoleMutation");

    function Harness() {
      const mutation = useConsoleMutation();
      return createElement(
        "div",
        null,
        createElement(
          "button",
          {
            type: "button",
            onClick: () => {
              mutation.run({
                safety: "confirm",
                recordName: "Nightly export",
                consequence: "This Job will stop and will not resume.",
                outcome: "Cancelled",
                execute,
              });
            },
          },
          "Cancel job",
        ),
        mutation.dialog,
      );
    }

    render(shell(createElement(Harness)));
    fireEvent.click(screen.getByRole("button", { name: "Cancel job" }));

    const dialog = await screen.findByRole("dialog");
    expect(dialog.textContent).toContain("Nightly export");
    expect(dialog.textContent).toContain("This Job will stop and will not resume.");
    expect(dialog.textContent).toContain("This cannot be undone.");
    const cancel = screen.getByRole("button", { name: "Cancel" });
    await waitFor(() => {
      expect(document.activeElement).toBe(cancel);
    });
    expect(execute).not.toHaveBeenCalled();
  });

  it("undoable shows Undo and the inverse runs", async () => {
    const execute = vi.fn(async () => {});
    const undo = vi.fn(async () => {});
    const { useConsoleMutation } = await import("@/components/feedback/useConsoleMutation");

    function Harness() {
      const mutation = useConsoleMutation();
      return createElement(
        "button",
        {
          type: "button",
          onClick: () => {
            mutation.run({
              safety: "undoable",
              recordName: "Nightly export",
              outcome: "Enabled",
              execute,
              undo,
            });
          },
        },
        "Enable",
      );
    }

    render(shell(createElement(Harness)));
    fireEvent.click(screen.getByRole("button", { name: "Enable" }));

    expect(await screen.findByText("Enabled — Nightly export")).toBeTruthy();
    const undoButton = await screen.findByRole("button", { name: "Undo" });
    fireEvent.click(undoButton);
    await waitFor(() => {
      expect(undo).toHaveBeenCalledTimes(1);
    });
    expect(execute).toHaveBeenCalledTimes(1);
  });

  it("a second click while submitting does not double-fire", async () => {
    let release: () => void = () => {};
    const execute = vi.fn(
      () =>
        new Promise<void>((resolve) => {
          release = resolve;
        }),
    );
    const { useConsoleMutation } = await import("@/components/feedback/useConsoleMutation");

    function Harness() {
      const mutation = useConsoleMutation();
      return createElement(
        "div",
        null,
        createElement(
          "button",
          {
            type: "button",
            onClick: () => {
              mutation.run({
                safety: "immediate",
                recordName: "Nightly export",
                outcome: "Enabled",
                execute,
              });
            },
          },
          "Run",
        ),
        mutation.dialog,
      );
    }

    render(shell(createElement(Harness)));
    const run = screen.getByRole("button", { name: "Run" });
    fireEvent.click(run);
    fireEvent.click(run);
    expect(execute).toHaveBeenCalledTimes(1);
    release();
    await waitFor(() => {
      expect(screen.getByText("Enabled — Nightly export")).toBeTruthy();
    });
    expect(execute).toHaveBeenCalledTimes(1);
  });

  it("keeps server detail out of the error notification title and copies it from the disclosure", async () => {
    const { useConsoleMutation } = await import("@/components/feedback/useConsoleMutation");

    function Harness() {
      const mutation = useConsoleMutation();
      return createElement(
        "button",
        {
          type: "button",
          onClick: () => {
            mutation.run({
              safety: "immediate",
              recordName: "Intake",
              outcome: "Saved",
              execute: () =>
                Promise.reject(new ApiError(500, "NO_SUCH_CODE", "Raw English detail", "req-9")),
            });
          },
        },
        "Save",
      );
    }

    render(shell(createElement(Harness)));
    fireEvent.click(screen.getByRole("button", { name: "Save" }));

    expect(await screen.findByText("Something went wrong. Try again.")).toBeTruthy();
    const summary = await screen.findByText("Details");
    fireEvent.click(summary);
    expect(screen.getByText("Raw English detail")).toBeTruthy();
    expect(screen.getByText("Request ID: req-9")).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "Copy details" }));
    await waitFor(() => {
      expect(copy.text).toHaveBeenCalledWith("Raw English detail\nRequest ID: req-9");
    });
  });

  it("routes a form error through the save summary and keeps server text in the disclosure", async () => {
    const { useConsoleMutation } = await import("@/components/feedback/useConsoleMutation");

    function Harness() {
      const mutation = useConsoleMutation();
      return createElement(
        "div",
        null,
        createElement(
          "button",
          {
            type: "button",
            onClick: () => {
              mutation.run({
                safety: "immediate",
                recordName: "Intake",
                outcome: "Saved",
                applyApiError: () => ({ mapped: [], unmapped: [] }),
                execute: () =>
                  Promise.reject(
                    new ApiError(500, "NO_SUCH_CODE", "Raw English detail", "req-9"),
                  ),
              });
            },
          },
          "Save",
        ),
        mutation.failure
          ? createElement(FormErrorSummary, { failure: mutation.failure })
          : null,
      );
    }

    render(shell(createElement(Harness)));
    fireEvent.click(screen.getByRole("button", { name: "Save" }));

    const alert = await screen.findByRole("alert");
    expect(alert.textContent).toContain("Something went wrong. Try again.");
    expect(alert.textContent).not.toMatch(/^Raw English detail/);
    expect(alert.querySelector("summary")?.textContent).toBe("Details");
    expect(alert.textContent).toContain("Raw English detail");
    expect(alert.textContent).toContain("req-9");
    fireEvent.click(screen.getByRole("button", { name: "Copy details" }));
    await waitFor(() => {
      expect(copy.text).toHaveBeenCalledWith("Raw English detail\nRequest ID: req-9");
    });
    expect(screen.queryByText("Saved — Intake")).toBeNull();
  });
});
