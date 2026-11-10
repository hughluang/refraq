/** @vitest-environment jsdom */

import { MantineProvider } from "@mantine/core";
import { notifications, notificationsStore } from "@mantine/notifications";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { createElement, type ReactNode } from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { servicePayload } from "@/features/model-services/ModelServiceForm";
import type { ModelServiceFormValues } from "@/features/model-services/types";
import { ApiError } from "@/lib/api";
import en from "@/locales/en-US/common.json";
import { ConsoleNotifications } from "@/providers/notification-provider";

const copy = en as Record<string, string>;
const submit = vi.hoisted(() => vi.fn());

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
  return new ApiError(422, "REQUEST_INVALID", "Request validation failed", "req-model", {}, details);
}

async function fillAndSave() {
  fireEvent.change(screen.getByRole("textbox", { name: "Display name" }), {
    target: { value: "Embed" },
  });
  fireEvent.change(screen.getByRole("textbox", { name: "Embeddings URL" }), {
    target: { value: "https://embed.example/v1/embeddings" },
  });
  fireEvent.change(screen.getByRole("textbox", { name: "Model" }), {
    target: { value: "text-embedding" },
  });
  fireEvent.click(screen.getByRole("button", { name: copy["actions.save"] }));
}

async function renderForm() {
  const { ModelServiceForm } = await import("@/features/model-services/ModelServiceForm");
  render(
    shell(
      createElement(ModelServiceForm, {
        opened: true,
        onSubmit: (...args: unknown[]) => submit(...args),
        onClose: () => undefined,
      }),
    ),
  );
}

describe("ModelServiceForm save", () => {
  beforeEach(() => {
    stubDomApis();
    submit.mockReset();
    resetNotifications();
  });

  afterEach(() => {
    cleanup();
    resetNotifications();
  });

  it("marks the mapped field, notifies once, and keeps the dialog free of an alert", async () => {
    submit.mockRejectedValue(
      rejection([
        { field: "display_name", message: "Name is taken" },
        { field: "retired", message: "Unknown field" },
      ]),
    );
    await renderForm();
    await fillAndSave();

    expect(await screen.findAllByRole("alert")).toHaveLength(1);
    const dialog = screen.getByRole("dialog", { name: copy["modelServices.create"] });
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
    submit.mockRejectedValue(rejection([{ field: "display_name", message: "Name is taken" }]));
    await renderForm();
    await fillAndSave();

    expect((await screen.findAllByText("Name is taken")).length).toBeGreaterThan(0);
    expect(screen.queryByRole("alert")).toBeNull();
    expect(
      screen.getByRole("dialog", { name: copy["modelServices.create"] }).querySelector("[role='alert']"),
    ).toBeNull();
    expect(screen.queryByText(copy["form.error.details"])).toBeNull();
  });

  it("edits a batch limit from 1 through 32 and submits that limit", async () => {
    submit.mockResolvedValue(undefined);
    await renderForm();
    const limit = screen.getByRole("textbox", { name: /Batch item limit/ });
    expect((limit as HTMLInputElement).value).toBe("32");
    fireEvent.change(limit, { target: { value: "0" } });
    fireEvent.click(screen.getByRole("button", { name: copy["actions.save"] }));
    expect(await screen.findByText(copy["modelServices.validation.batch_limit"])).toBeTruthy();
    expect(submit).not.toHaveBeenCalled();

    fireEvent.change(limit, { target: { value: "8" } });
    await fillAndSave();
    const values = submit.mock.calls[0][0] as ModelServiceFormValues;
    expect(values.batch_limit).toBe(8);
    expect(servicePayload(values).batch_limit).toBe(8);
  });

  it("keeps the in-use model editable", async () => {
    const { ModelServiceForm } = await import("@/features/model-services/ModelServiceForm");
    render(
      shell(
        createElement(ModelServiceForm, {
          opened: true,
          service: {
            id: "svc_1",
            purpose: "embedding",
            protocol: "openai_compat",
            display_name: "Embed",
            url: "https://embed.example/v1/embeddings",
            model: "text-embedding",
            timeout_sec: 30,
            batch_limit: 16,
            has_secret: true,
            in_use: true,
            created_at: "2026-01-01T00:00:00Z",
            updated_at: "2026-01-01T00:00:00Z",
          },
          onSubmit: (...args: unknown[]) => submit(...args),
          onClose: () => undefined,
        }),
      ),
    );
    const model = screen.getByRole("textbox", { name: "Model" });
    expect(model).not.toHaveProperty("disabled", true);
    expect((model as HTMLInputElement).readOnly).toBe(false);
    fireEvent.click(screen.getByRole("button", { name: "Model Description" }));
    expect(await screen.findByText(copy["modelServices.fields.model.inUse"])).toBeTruthy();
    expect(screen.queryByText(/cannot change while this service is in use/i)).toBeNull();
  });
});
