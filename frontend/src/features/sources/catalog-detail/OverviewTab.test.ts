/** @vitest-environment jsdom */

import { MantineProvider } from "@mantine/core";
import { notifications, notificationsStore } from "@mantine/notifications";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { createElement, type ReactNode } from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { ApiError } from "@/lib/api";
import en from "@/locales/en-US/common.json";
import { ConsoleNotifications } from "@/providers/notification-provider";
import type { CatalogObject } from "@/features/sources/types";

const messages = en as Record<string, string>;

const semanticsApi = vi.hoisted(() => ({
  patch: vi.fn(),
}));

function translate(key: string, options?: Record<string, unknown>) {
  const template = messages[key] ?? key;
  if (!options) return template;
  return template.replace(/\{\{(\w+)\}\}/g, (_, name: string) =>
    String(options[name] ?? ""),
  );
}

vi.mock("@refinedev/core", () => ({
  useTranslate: () => translate,
  useNotification: () => ({ open: vi.fn() }),
}));

vi.mock("@/features/sources/api/semantics", () => ({
  patchObjectSemantics: (...args: unknown[]) => semanticsApi.patch(...args),
}));

const OBJECT: CatalogObject = {
  id: "obj-1",
  locator_key: "public.orders",
  source_id: "src-1",
  object_type: "table",
  schema_name: "public",
  name: "orders",
  comment: null,
  primary_key: ["id"],
  business_name: "Orders",
  business_description: "Order rows",
  object_category: null,
  grain_description: "",
  business_primary_key: [],
  evidence_summary: [],
  open_questions: [],
  semantic_source: null,
  business_semantics_ready: false,
  semantics_updated_at: null,
  columns: [],
  foreign_keys: [],
  indexes: [],
  ddl: null,
  is_present: true,
  collected_at: null,
};

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
  HTMLElement.prototype.scrollIntoView = () => {};
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

function overviewForm() {
  const form = document.querySelector("form");
  if (!form) throw new Error("missing overview form");
  return form;
}

async function saveOverview() {
  const { OverviewTab } = await import("@/features/sources/catalog-detail/OverviewTab");
  render(
    shell(
      createElement(OverviewTab, {
        object: OBJECT,
        writable: true,
        onSaved: () => {},
      }),
    ),
  );
  fireEvent.click(screen.getByRole("button", { name: messages["catalog.semantics.saveObject"] }));
}

describe("OverviewTab save", () => {
  beforeEach(() => {
    stubDomApis();
    semanticsApi.patch.mockReset();
    resetNotifications();
  });

  afterEach(() => {
    cleanup();
    resetNotifications();
  });

  it("shows one error notification and no save alert when semantics save is rejected", async () => {
    semanticsApi.patch.mockRejectedValue(
      new ApiError(500, "NO_SUCH_CODE", "Raw English detail", "req-overview"),
    );
    await saveOverview();

    expect(await screen.findAllByRole("alert")).toHaveLength(1);
    expect(overviewForm().querySelector("[role='alert']")).toBeNull();
    const title = screen.getByText(messages["problems.unknown"]);
    expect(title.closest("details")).toBeNull();
    fireEvent.click(screen.getByText(messages["form.error.details"]));
    expect(screen.getByText("Raw English detail").closest("details")).toBeTruthy();
    expect(overviewForm().textContent).not.toContain("Raw English detail");
  });

  it("marks the business name and sends no notification when every detail maps", async () => {
    semanticsApi.patch.mockRejectedValue(
      new ApiError(422, "REQUEST_INVALID", "Request validation failed", "req-full", {}, [
        { field: "business_name", message: "Name was rejected" },
      ]),
    );
    await saveOverview();

    expect(await screen.findByText("Name was rejected")).toBeTruthy();
    expect(screen.queryByRole("alert")).toBeNull();
    expect(overviewForm().querySelector("[role='alert']")).toBeNull();
    expect(screen.queryByText(messages["form.error.details"])).toBeNull();
  });

  it("marks the mapped field and discloses only the unmapped detail", async () => {
    semanticsApi.patch.mockRejectedValue(
      new ApiError(422, "REQUEST_INVALID", "Request validation failed", "req-part", {}, [
        { field: "business_name", message: "Name was rejected" },
        { field: "retired", message: "Unknown field" },
      ]),
    );
    await saveOverview();

    expect(await screen.findAllByRole("alert")).toHaveLength(1);
    expect(overviewForm().querySelector("[role='alert']")).toBeNull();
    expect(screen.getByText("Name was rejected")).toBeTruthy();
    fireEvent.click(screen.getByText(messages["form.error.details"]));
    const disclosure = screen.getByText(messages["form.error.details"]).closest("details");
    expect(disclosure?.textContent).toContain("retired: Unknown field");
    expect(disclosure?.textContent).not.toContain("Name was rejected");
    expect(overviewForm().textContent).not.toContain("Unknown field");
  });
});
