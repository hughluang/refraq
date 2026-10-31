/** @vitest-environment jsdom */

import { MantineProvider } from "@mantine/core";
import { notifications, notificationsStore } from "@mantine/notifications";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { createElement, type ReactNode } from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { ApiError } from "@/lib/api";
import en from "@/locales/en-US/common.json";
import { ConsoleNotifications } from "@/providers/notification-provider";

const copy = en as Record<string, string>;

const createDictionary = vi.hoisted(() => vi.fn());

vi.mock("@/features/dictionaries/api", () => ({
  createDictionary: (...args: unknown[]) => createDictionary(...args),
}));

vi.mock("@refinedev/core", () => ({
  useTranslate: () => (key: string, options?: Record<string, unknown>) => {
    const template = copy[key] ?? key;
    if (!options) return template;
    return template.replace(/\{\{(\w+)\}\}/g, (_, name: string) =>
      String(options[name] ?? ""),
    );
  },
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

function rejection(details: { field: string; message: string }[]) {
  return new ApiError(422, "REQUEST_INVALID", "Request validation failed", "req-dict", {}, details);
}

async function fillAndSave() {
  fireEvent.change(screen.getByLabelText(/^Name/), { target: { value: "palette" } });
  fireEvent.change(screen.getByLabelText(/^Display name/), { target: { value: "Palette" } });
  fireEvent.change(screen.getByLabelText(/^Code/), { target: { value: "red" } });
  fireEvent.click(screen.getByRole("button", { name: copy["dictionaries.create.submit"] }));
}

describe("CreateDictionaryModal save", () => {
  beforeEach(() => {
    stubDomApis();
    createDictionary.mockReset();
    resetNotifications();
  });

  afterEach(() => {
    cleanup();
    resetNotifications();
  });

  it("marks the mapped field, notifies once, and keeps the dialog free of an alert", async () => {
    createDictionary.mockRejectedValue(
      rejection([
        { field: "name", message: "Name is taken" },
        { field: "retired", message: "Unknown field" },
      ]),
    );
    const { CreateDictionaryModal } = await import(
      "@/features/dictionaries/CreateDictionaryModal"
    );
    render(
      shell(
        createElement(CreateDictionaryModal, {
          opened: true,
          onClose: () => undefined,
          onCreated: () => undefined,
        }),
      ),
    );
    await fillAndSave();

    expect(await screen.findAllByRole("alert")).toHaveLength(1);
    const dialog = screen.getByRole("dialog", { name: copy["dictionaries.create.title"] });
    expect(dialog.querySelector("[role='alert']")).toBeNull();
    expect((await screen.findAllByText("Name is taken")).length).toBeGreaterThan(0);
    fireEvent.click(screen.getByText(copy["form.error.details"]));
    const disclosure = screen.getByText(copy["form.error.details"]).closest("details");
    expect(disclosure?.textContent).toContain("retired: Unknown field");
    expect(disclosure?.textContent).not.toContain("Name is taken");
    expect(dialog.textContent).not.toContain("Unknown field");
    expect(dialog.textContent).not.toContain("Request validation failed");
  });

  it("marks every mapped field and sends no notification when the 422 is fully mapped", async () => {
    createDictionary.mockRejectedValue(
      rejection([{ field: "name", message: "Name is taken" }]),
    );
    const { CreateDictionaryModal } = await import(
      "@/features/dictionaries/CreateDictionaryModal"
    );
    render(
      shell(
        createElement(CreateDictionaryModal, {
          opened: true,
          onClose: () => undefined,
          onCreated: () => undefined,
        }),
      ),
    );
    await fillAndSave();

    expect((await screen.findAllByText("Name is taken")).length).toBeGreaterThan(0);
    expect(screen.queryByRole("alert")).toBeNull();
    expect(
      screen
        .getByRole("dialog", { name: copy["dictionaries.create.title"] })
        .querySelector("[role='alert']"),
    ).toBeNull();
    expect(screen.queryByText(copy["form.error.details"])).toBeNull();
  });
});
