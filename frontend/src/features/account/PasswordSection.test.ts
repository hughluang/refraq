/** @vitest-environment jsdom */

import { MantineProvider } from "@mantine/core";
import { notifications, notificationsStore } from "@mantine/notifications";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { createElement, type ReactNode } from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { ApiError } from "@/lib/api";
import { ConsoleNotifications } from "@/providers/notification-provider";

const changePassword = vi.hoisted(() => ({
  run: vi.fn(),
}));

vi.mock("@/features/account/api", () => ({
  changeAccountPassword: (...args: unknown[]) => changePassword.run(...args),
}));

vi.mock("@refinedev/core", () => ({
  useTranslate: () => (key: string, options?: Record<string, unknown>) => {
    const dictionary: Record<string, string> = {
      "account.section.password": "Password",
      "account.password.save": "Update password",
      "account.password.success": "Password updated; other sessions were signed out",
      "account.password.hint": "Your current browser session stays signed in.",
      "account.fields.currentPassword": "Current password",
      "account.fields.newPassword": "New password",
      "account.fields.confirmPassword": "Confirm new password",
      "account.validation.required": "Required",
      "account.validation.password": "Password must be at least 6 characters",
      "account.validation.passwordMatch": "New passwords do not match",
      "account.title": "Account",
      "problems.unknown": "Something went wrong. Try again.",
      "form.error.details": "Details",
      "form.error.copy": "Copy details",
      "form.dialog.close": "Close",
      "common.cancel": "Cancel",
      "common.requestId": "Request ID",
      "common.copy.success": "Copied",
      "common.copy.failed": "Copy failed",
      "auth.password.visibility": "Show password",
    };
    const template = dictionary[key] ?? key;
    if (!options) return template;
    return template.replace(/\{\{(\w+)\}\}/g, (_, name: string) =>
      String(options[name] ?? ""),
    );
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

function resetNotifications() {
  const state = notificationsStore.getState();
  for (const item of [...state.notifications, ...state.queue]) {
    notifications.hide(item.id);
  }
  notifications.clean();
}

function shell(node: ReactNode) {
  return createElement(
    MantineProvider,
    { env: "test" },
    createElement(ConsoleNotifications),
    node,
  );
}

async function openAndSubmit() {
  fireEvent.click(screen.getByRole("button", { name: "Password" }));
  fireEvent.change(await screen.findByLabelText(/^Current password/), {
    target: { value: "secret1" },
  });
  fireEvent.change(screen.getByLabelText(/^New password/), {
    target: { value: "secret2" },
  });
  fireEvent.change(screen.getByLabelText(/^Confirm new password/), {
    target: { value: "secret2" },
  });
  fireEvent.click(screen.getByRole("button", { name: "Update password" }));
}

describe("PasswordSection", () => {
  beforeEach(() => {
    stubDomApis();
    changePassword.run.mockReset();
    resetNotifications();
  });

  afterEach(() => {
    cleanup();
    resetNotifications();
  });

  it("shows one error notification and no alert in the dialog when the save is rejected", async () => {
    changePassword.run.mockRejectedValue(
      new ApiError(500, "NO_SUCH_CODE", "Raw English detail", "req-pw"),
    );
    const { PasswordSection } = await import("@/features/account/PasswordSection");
    render(shell(createElement(PasswordSection)));
    await openAndSubmit();

    expect(await screen.findAllByRole("alert")).toHaveLength(1);
    const dialog = screen.getByRole("dialog");
    expect(dialog.querySelector("[role='alert']")).toBeNull();
    const title = screen.getByText("Something went wrong. Try again.");
    expect(title.closest("details")).toBeNull();
    fireEvent.click(screen.getByText("Details"));
    expect(screen.getByText("Raw English detail").closest("details")).toBeTruthy();
    expect(dialog.textContent).not.toContain("Raw English detail");
  });

  it("marks the password field and sends no notification when every detail maps", async () => {
    changePassword.run.mockRejectedValue(
      new ApiError(422, "REQUEST_INVALID", "Request validation failed", "req-full", {}, [
        { field: "current_password", message: "Wrong password" },
      ]),
    );
    const { PasswordSection } = await import("@/features/account/PasswordSection");
    render(shell(createElement(PasswordSection)));
    await openAndSubmit();

    expect(await screen.findByText("Wrong password")).toBeTruthy();
    expect(screen.queryByRole("alert")).toBeNull();
    expect(screen.getByRole("dialog").querySelector("[role='alert']")).toBeNull();
    expect(screen.queryByText("Details")).toBeNull();
  });

  it("marks the mapped password field and discloses only the unmapped detail", async () => {
    changePassword.run.mockRejectedValue(
      new ApiError(422, "REQUEST_INVALID", "Request validation failed", "req-part", {}, [
        { field: "current_password", message: "Wrong password" },
        { field: "retired", message: "Unknown field" },
      ]),
    );
    const { PasswordSection } = await import("@/features/account/PasswordSection");
    render(shell(createElement(PasswordSection)));
    await openAndSubmit();

    expect(await screen.findAllByRole("alert")).toHaveLength(1);
    expect(screen.getByRole("dialog").querySelector("[role='alert']")).toBeNull();
    expect(screen.getByText("Wrong password")).toBeTruthy();
    fireEvent.click(screen.getByText("Details"));
    const disclosure = screen.getByText("Details").closest("details");
    expect(disclosure?.textContent).toContain("retired: Unknown field");
    expect(disclosure?.textContent).not.toContain("Wrong password");
    expect(screen.getByRole("dialog").textContent).not.toContain("Unknown field");
  });
});
