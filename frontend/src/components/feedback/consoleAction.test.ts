/** @vitest-environment jsdom */

import { MantineProvider } from "@mantine/core";
import { notifications, notificationsStore } from "@mantine/notifications";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { createElement, type ReactNode } from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

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

function resetNotifications() {
  const state = notificationsStore.getState();
  for (const item of [...state.notifications, ...state.queue]) {
    notifications.hide(item.id);
  }
  notifications.clean();
}

describe("console actions", () => {
  beforeEach(() => {
    stubDomApis();
    copy.text.mockClear();
    resetNotifications();
  });

  afterEach(() => {
    cleanup();
    resetNotifications();
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

  it("shows one error notification when a save is rejected", async () => {
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
        createElement(
          "span",
          { "data-testid": "stored-failure" },
          "failure" in mutation ? "stored" : "none",
        ),
      );
    }

    render(shell(createElement(Harness)));
    fireEvent.click(screen.getByRole("button", { name: "Save" }));

    expect(await screen.findAllByRole("alert")).toHaveLength(1);
    const title = screen.getByText("Something went wrong. Try again.");
    expect(title.closest("details")).toBeNull();
    fireEvent.click(screen.getByText("Details"));
    expect(screen.getByText("Raw English detail").closest("details")).toBeTruthy();
    expect(screen.getByText("Request ID: req-9").closest("details")).toBeTruthy();
    expect(screen.queryByText("Saved — Intake")).toBeNull();
    expect(screen.getByTestId("stored-failure").textContent).toBe("none");
  });

  it("shows one error notification when a 422 matches no field", async () => {
    const { useConsoleMutation } = await import("@/components/feedback/useConsoleMutation");
    const { useConsoleForm } = await import("@/components/form/useConsoleForm");

    function Harness() {
      const mutation = useConsoleMutation();
      const form = useConsoleForm({ initialValues: { account: "", host: "" } });
      return createElement(
        "div",
        null,
        createElement("input", { "aria-label": "Account", ...form.fieldProps("account") }),
        createElement("input", { "aria-label": "Host", ...form.fieldProps("host") }),
        createElement("pre", { "data-testid": "errors" }, JSON.stringify(form.errors)),
        createElement(
          "button",
          {
            type: "button",
            onClick: () => {
              mutation.run({
                safety: "immediate",
                recordName: "Intake",
                outcome: "Saved",
                applyApiError: (error) => form.applyApiError(error),
                execute: () =>
                  Promise.reject(
                    new ApiError(422, "REQUEST_INVALID", "Request validation failed", "req-422", {}, [
                      { field: "missing", message: "Nope" },
                    ]),
                  ),
              });
            },
          },
          "Save",
        ),
      );
    }

    render(shell(createElement(Harness)));
    fireEvent.click(screen.getByRole("button", { name: "Save" }));

    expect(await screen.findAllByRole("alert")).toHaveLength(1);
    expect(screen.getByTestId("errors").textContent).toBe("{}");
    fireEvent.click(screen.getByText("Details"));
    const disclosure = screen.getByText("missing: Nope").closest("details");
    expect(disclosure).toBeTruthy();
    expect(disclosure?.textContent).toContain("Request validation failed");
    expect(disclosure?.textContent).not.toContain("Saved — Intake");
  });

  it("marks every mapped field and sends no notification for a fully mapped 422", async () => {
    const { useConsoleMutation } = await import("@/components/feedback/useConsoleMutation");
    const { useConsoleForm } = await import("@/components/form/useConsoleForm");

    function Harness() {
      const mutation = useConsoleMutation();
      const form = useConsoleForm({ initialValues: { account: "", host: "" } });
      return createElement(
        "div",
        null,
        createElement("input", { "aria-label": "Account", ...form.fieldProps("account") }),
        createElement("input", { "aria-label": "Host", ...form.fieldProps("host") }),
        createElement("pre", { "data-testid": "errors" }, JSON.stringify(form.errors)),
        createElement(
          "button",
          {
            type: "button",
            onClick: () => {
              mutation.run({
                safety: "immediate",
                recordName: "Intake",
                outcome: "Saved",
                applyApiError: (error) => form.applyApiError(error),
                execute: () =>
                  Promise.reject(
                    new ApiError(422, "REQUEST_INVALID", "Request validation failed", "req-full", {}, [
                      { field: "account", message: "Field required" },
                      { field: "host", message: "Bad host" },
                    ]),
                  ),
              });
            },
          },
          "Save",
        ),
      );
    }

    render(shell(createElement(Harness)));
    fireEvent.click(screen.getByRole("button", { name: "Save" }));

    await waitFor(() => {
      const errors = screen.getByTestId("errors").textContent ?? "";
      expect(errors).toContain('"account":"Field required"');
      expect(errors).toContain('"host":"Bad host"');
    });
    expect(screen.queryByRole("alert")).toBeNull();
    expect(screen.queryByText("Details")).toBeNull();
    expect(screen.queryByText("Saved — Intake")).toBeNull();
  });

  it("marks the mapped fields and discloses only the unmapped details", async () => {
    const { useConsoleMutation } = await import("@/components/feedback/useConsoleMutation");
    const { useConsoleForm } = await import("@/components/form/useConsoleForm");

    function Harness() {
      const mutation = useConsoleMutation();
      const form = useConsoleForm({ initialValues: { account: "", host: "" } });
      return createElement(
        "div",
        null,
        createElement("input", { "aria-label": "Account", ...form.fieldProps("account") }),
        createElement("input", { "aria-label": "Host", ...form.fieldProps("host") }),
        createElement("pre", { "data-testid": "errors" }, JSON.stringify(form.errors)),
        createElement(
          "button",
          {
            type: "button",
            onClick: () => {
              mutation.run({
                safety: "immediate",
                recordName: "Intake",
                outcome: "Saved",
                applyApiError: (error) => form.applyApiError(error),
                execute: () =>
                  Promise.reject(
                    new ApiError(422, "REQUEST_INVALID", "Request validation failed", "req-part", {}, [
                      { field: "account", message: "Field required" },
                      { field: "missing", message: "Nope" },
                    ]),
                  ),
              });
            },
          },
          "Save",
        ),
      );
    }

    render(shell(createElement(Harness)));
    fireEvent.click(screen.getByRole("button", { name: "Save" }));

    expect(await screen.findAllByRole("alert")).toHaveLength(1);
    await waitFor(() => {
      const errors = screen.getByTestId("errors").textContent ?? "";
      expect(errors).toContain('"account":"Field required"');
      expect(errors).not.toContain("Nope");
    });
    fireEvent.click(screen.getByText("Details"));
    const disclosure = screen.getByText("Details").closest("details");
    expect(disclosure?.textContent).toContain("missing: Nope");
    expect(disclosure?.textContent).not.toContain("Field required");
    expect(disclosure?.textContent).not.toContain("account:");
  });

  it("shows one error notification when a 422 carries no details", async () => {
    const { useConsoleMutation } = await import("@/components/feedback/useConsoleMutation");
    const { useConsoleForm } = await import("@/components/form/useConsoleForm");

    function Harness() {
      const mutation = useConsoleMutation();
      const form = useConsoleForm({ initialValues: { account: "" } });
      return createElement(
        "button",
        {
          type: "button",
          onClick: () => {
            mutation.run({
              safety: "immediate",
              recordName: "Intake",
              outcome: "Saved",
              applyApiError: (error) => form.applyApiError(error),
              execute: () =>
                Promise.reject(
                  new ApiError(422, "REQUEST_INVALID", "Request validation failed", "req-empty", {}, []),
                ),
            });
          },
        },
        "Save",
      );
    }

    render(shell(createElement(Harness)));
    fireEvent.click(screen.getByRole("button", { name: "Save" }));

    expect(await screen.findAllByRole("alert")).toHaveLength(1);
    fireEvent.click(screen.getByText("Details"));
    expect(screen.getByText("Request validation failed").closest("details")).toBeTruthy();
    expect(screen.queryByText("Saved — Intake")).toBeNull();
  });
});
