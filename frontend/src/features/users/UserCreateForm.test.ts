/** @vitest-environment jsdom */

import { MantineProvider } from "@mantine/core";
import { notifications, notificationsStore } from "@mantine/notifications";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { createElement, type ReactNode } from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { ApiError } from "@/lib/api";
import en from "@/locales/en-US/common.json";
import { ConsoleNotifications } from "@/providers/notification-provider";

const messages = en as Record<string, string>;

const finish = vi.hoisted(() => ({
  run: vi.fn(),
}));

function translate(key: string, options?: Record<string, unknown>) {
  const template = messages[key] ?? key;
  if (!options) return template;
  return template.replace(/\{\{(\w+)\}\}/g, (_, name: string) =>
    String(options[name] ?? ""),
  );
}

vi.mock("@refinedev/core", () => ({
  matchResourceFromRoute: () => ({ found: false }),
  useTranslate: () => translate,
  useForm: () => ({ onFinish: finish.run }),
}));

vi.mock("@/components/layout/PageChrome", () => ({
  PageChrome: ({
    children,
    actions,
  }: {
    children?: ReactNode;
    actions?: ReactNode;
  }) => createElement("div", null, actions, children),
}));

vi.mock("@/components/navigation/ConsoleLink", () => ({
  ConsoleLink: ({ children }: { children?: ReactNode }) =>
    createElement("a", null, children),
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

function createForm() {
  const form = document.getElementById("user-create-form");
  if (!form) throw new Error("missing create form");
  return form;
}

async function fillAndSubmit() {
  fireEvent.change(screen.getByLabelText(/^Account/), { target: { value: "ada" } });
  fireEvent.change(screen.getByLabelText(/^Display name/), { target: { value: "Ada" } });
  fireEvent.change(screen.getByLabelText(/^Initial password/), {
    target: { value: "secret1" },
  });
  fireEvent.click(screen.getByRole("button", { name: "Create" }));
}

describe("UserCreateForm save", () => {
  beforeEach(() => {
    stubDomApis();
    finish.run.mockReset();
    resetNotifications();
  });

  afterEach(() => {
    cleanup();
    resetNotifications();
  });

  it("shows one error notification and no save alert when create is rejected", async () => {
    finish.run.mockRejectedValue(
      new ApiError(500, "NO_SUCH_CODE", "Raw English detail", "req-create"),
    );
    const { UserCreateForm } = await import("@/features/users/UserCreateForm");
    render(shell(createElement(UserCreateForm)));
    await fillAndSubmit();

    expect(await screen.findAllByRole("alert")).toHaveLength(1);
    expect(createForm().querySelector("[role='alert']")).toBeNull();
    const title = screen.getByText(messages["problems.unknown"]);
    expect(title.closest("details")).toBeNull();
    fireEvent.click(screen.getByText(messages["form.error.details"]));
    expect(screen.getByText("Raw English detail").closest("details")).toBeTruthy();
    expect(createForm().textContent).not.toContain("Raw English detail");
  });

  it("marks the account field and sends no notification when every detail maps", async () => {
    finish.run.mockRejectedValue(
      new ApiError(422, "REQUEST_INVALID", "Request validation failed", "req-full", {}, [
        { field: "account", message: "Account is taken" },
      ]),
    );
    const { UserCreateForm } = await import("@/features/users/UserCreateForm");
    render(shell(createElement(UserCreateForm)));
    await fillAndSubmit();

    expect(await screen.findByText("Account is taken")).toBeTruthy();
    expect(screen.queryByRole("alert")).toBeNull();
    expect(createForm().querySelector("[role='alert']")).toBeNull();
    expect(screen.queryByText(messages["form.error.details"])).toBeNull();
  });

  it("marks the mapped field and discloses only the unmapped detail", async () => {
    finish.run.mockRejectedValue(
      new ApiError(422, "REQUEST_INVALID", "Request validation failed", "req-part", {}, [
        { field: "account", message: "Account is taken" },
        { field: "retired", message: "Unknown field" },
      ]),
    );
    const { UserCreateForm } = await import("@/features/users/UserCreateForm");
    render(shell(createElement(UserCreateForm)));
    await fillAndSubmit();

    expect(await screen.findAllByRole("alert")).toHaveLength(1);
    expect(createForm().querySelector("[role='alert']")).toBeNull();
    expect(screen.getByText("Account is taken")).toBeTruthy();
    fireEvent.click(screen.getByText(messages["form.error.details"]));
    const disclosure = screen.getByText(messages["form.error.details"]).closest("details");
    expect(disclosure?.textContent).toContain("retired: Unknown field");
    expect(disclosure?.textContent).not.toContain("Account is taken");
    expect(createForm().textContent).not.toContain("Unknown field");
  });
});
