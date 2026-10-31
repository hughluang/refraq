/** @vitest-environment jsdom */

import { MantineProvider } from "@mantine/core";
import { notifications, notificationsStore } from "@mantine/notifications";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { createElement, type ReactNode } from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { ColumnsTab } from "@/features/sources/catalog-detail/ColumnsTab";
import { ApiError } from "@/lib/api";
import en from "@/locales/en-US/common.json";
import { ConsoleNotifications } from "@/providers/notification-provider";
import type { CatalogColumn, CatalogObject } from "@/features/sources/types";

const copy = en as Record<string, string>;

type PageQuery = { limit: number; offset: number };
type OffsetPage = {
  items: readonly unknown[];
  total: number;
  limit: number;
  offset: number;
};

const pageApi = vi.hoisted(() => ({
  real: null as null | ((items: readonly unknown[], query: PageQuery) => OffsetPage),
  fail: false,
}));

function translate(key: string, options?: Record<string, unknown>) {
  const template = copy[key] ?? key;
  if (!options) return template;
  return template.replace(/\{\{(\w+)\}\}/g, (_, name: string) => String(options[name] ?? ""));
}

vi.mock("@refinedev/core", () => ({
  useTranslate: () => translate,
  useNotification: () => ({ open: vi.fn() }),
}));

vi.mock("@/lib/pagination", async () => {
  const actual = await vi.importActual<typeof import("@/lib/pagination")>("@/lib/pagination");
  pageApi.real = actual.offsetPageFromItems;
  return {
    ...actual,
    offsetPageFromItems: (items: readonly unknown[], query: PageQuery) => {
      if (pageApi.fail) {
        throw new ApiError(500, "NO_SUCH_CODE", "columns unavailable", "req-columns");
      }
      const real = pageApi.real;
      if (!real) throw new Error("missing page adapter");
      return real(items, query);
    },
  };
});

function column(): CatalogColumn {
  return {
    id: "col-amount",
    locator_key: "public.orders.amount",
    name: "amount",
    data_type: "numeric",
    nullable: true,
    business_name: null,
    business_description: null,
    ordinal: 1,
    is_present: true,
  };
}

const OBJECT: CatalogObject = {
  id: "obj-1",
  locator_key: "public.orders",
  source_id: "src-1",
  object_type: "table",
  schema_name: "public",
  name: "orders",
  comment: null,
  primary_key: ["amount"],
  business_name: "Orders",
  business_description: null,
  columns: [column()],
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

function renderColumns() {
  render(
    shell(
      createElement(ColumnsTab, {
        object: OBJECT,
        writable: false,
        onSaved: () => {},
        reloadEpoch: 0,
      }),
    ),
  );
}

describe("ColumnsTab load", () => {
  beforeEach(() => {
    stubDomApis();
    pageApi.fail = false;
    resetNotifications();
  });

  afterEach(() => {
    cleanup();
    resetNotifications();
  });

  it("shows unloaded and one error notification when the column list fails to load", async () => {
    pageApi.fail = true;
    renderColumns();

    const status = await screen.findByRole("button", { name: copy["status.unloaded"] });
    const table = screen.getByRole("table");
    expect(table.contains(status)).toBe(true);
    expect(table.textContent).not.toContain("columns unavailable");
    expect(screen.queryByText("amount")).toBeNull();
    const alerts = screen.getAllByRole("alert");
    expect(alerts).toHaveLength(1);
    expect(alerts[0]?.textContent).toContain(copy["problems.unknown"]);
    expect(alerts[0]?.textContent).toContain("req-columns");

    pageApi.fail = false;
    fireEvent.click(screen.getByRole("button", { name: copy["common.retry"] }));

    expect(await screen.findByText("amount")).toBeTruthy();
    expect(screen.queryByRole("button", { name: copy["status.unloaded"] })).toBeNull();
  });

  it("keeps loaded columns and sends one notification when a later load fails", async () => {
    renderColumns();
    expect(await screen.findByText("amount")).toBeTruthy();
    expect(screen.queryByRole("alert")).toBeNull();

    pageApi.fail = true;
    fireEvent.change(screen.getByRole("textbox", { name: copy["catalog.columns.search"] }), {
      target: { value: "zzz" },
    });

    expect(await screen.findByText("amount")).toBeTruthy();
    expect(screen.queryByRole("button", { name: copy["status.unloaded"] })).toBeNull();
    const alerts = screen.getAllByRole("alert");
    expect(alerts).toHaveLength(1);
    expect(alerts[0]?.textContent).toContain(copy["problems.unknown"]);
    expect(screen.getByRole("button", { name: copy["common.retry"] })).toBeTruthy();
  });
});
