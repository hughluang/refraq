/** @vitest-environment jsdom */
import { MantineProvider } from "@mantine/core";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { createElement } from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import en from "@/locales/en-US/common.json";
import type { CatalogColumn, SemanticsChange } from "@/features/sources/types";
import { HistoryTab } from "./HistoryTab";

const api = vi.hoisted(() => ({
  listChanges: vi.fn(),
}));

vi.mock("@refinedev/core", () => ({
  useTranslate: () => (key: string, options?: Record<string, unknown>) =>
    ((en as Record<string, string>)[key] ?? key).replace(
      /\{\{(\w+)\}\}/g,
      (_, name: string) => String(options?.[name] ?? ""),
    ),
}));

vi.mock("@/features/sources/api/catalog", () => ({
  listSemanticsChanges: api.listChanges,
}));

vi.mock("@/providers/notification-provider", () => ({
  presentConsoleNotification: vi.fn(),
  dismissConsoleNotification: vi.fn(),
}));

const columns: CatalogColumn[] = [
  {
    id: "col-1",
    locator_key: "col/pg/demo/public/table/orders/column/status",
    name: "status",
    data_type: "varchar",
    nullable: false,
    business_name: "Order Status",
    business_description: null,
    ordinal: 1,
    is_present: true,
  },
  {
    id: "col-2",
    locator_key: "col/pg/demo/public/table/orders/column/amount",
    name: "amount",
    data_type: "numeric",
    nullable: false,
    business_name: null,
    business_description: null,
    ordinal: 2,
    is_present: true,
  },
];

const changes: SemanticsChange[] = [
  {
    id: "chg-1",
    object_id: "obj-1",
    column_id: null,
    field_name: "business_name",
    old_value: null,
    new_value: "Customer Orders",
    semantic_source: "user_input",
    actor_user_id: "u-1",
    actor_display_name: "Alice",
    created_at: "2026-11-10T10:00:00Z",
  },
  {
    id: "chg-2",
    object_id: "obj-1",
    column_id: null,
    field_name: "evidence_summary",
    old_value: ["Legacy note", "Shared key"],
    new_value: ["Shared key", "Verified in warehouse"],
    semantic_source: "mcp",
    actor_user_id: null,
    actor_display_name: "Catalog Agent",
    created_at: "2026-11-10T11:00:00Z",
  },
  {
    id: "chg-3",
    object_id: "obj-1",
    column_id: "col-1",
    column_name: "status",
    field_name: "enum_catalog",
    old_value: [
      { code: "O", label: "Open" },
      { code: "P", label: "Pending" },
    ],
    new_value: [
      { code: "O", label: "Open Order" },
      { code: "C", label: "Closed" },
    ],
    semantic_source: "user_input",
    actor_user_id: "u-1",
    actor_display_name: "Alice",
    created_at: "2026-11-10T12:00:00Z",
  },
  {
    id: "chg-4",
    object_id: "obj-1",
    column_id: "col-2",
    field_name: "column_semantics",
    old_value: { semantic_type: "number", unit: null },
    new_value: { semantic_type: "currency", unit: "USD" },
    semantic_source: "mcp",
    actor_user_id: null,
    actor_display_name: null,
    created_at: "2026-11-10T13:00:00Z",
  },
];

function mount(props: Partial<Parameters<typeof HistoryTab>[0]> = {}) {
  return render(
    createElement(
      MantineProvider,
      { env: "test" },
      createElement(HistoryTab, {
        objectId: "obj-1",
        columns,
        ...props,
      }),
    ),
  );
}

beforeEach(() => {
  vi.clearAllMocks();
  api.listChanges.mockResolvedValue({
    items: changes,
    total: changes.length,
    limit: 50,
    offset: 0,
  });
  Object.defineProperty(window, "matchMedia", {
    value: (query: string) => ({
      matches: false,
      media: query,
      addEventListener: vi.fn(),
      removeEventListener: vi.fn(),
    }),
    configurable: true,
  });
  globalThis.ResizeObserver = class {
    observe() {}
    unobserve() {}
    disconnect() {}
  };
  Element.prototype.scrollIntoView = vi.fn();
});

afterEach(cleanup);

describe("HistoryTab", () => {
  it("does not fetch or render when listEnabled is false", async () => {
    mount({ listEnabled: false });
    await new Promise((resolve) => setTimeout(resolve, 20));
    expect(api.listChanges).not.toHaveBeenCalled();
    expect(screen.queryByRole("table")).toBeNull();
  });

  it("renders structured diffs, clickable column targets, and actor provenance", async () => {
    const onOpenColumn = vi.fn();
    mount({ onOpenColumn });

    expect(await screen.findByText("Customer Orders")).toBeTruthy();
    expect(screen.getAllByText(en["catalog.history.emptyValue"]).length).toBeGreaterThanOrEqual(1);

    // String array diff
    expect(screen.getByText("− Legacy note")).toBeTruthy();
    expect(screen.getByText("+ Verified in warehouse")).toBeTruthy();

    // enum_catalog diff by code
    expect(screen.getByText("− P: Pending")).toBeTruthy();
    expect(screen.getByText("~ O: Open → Open Order")).toBeTruthy();
    expect(screen.getByText("+ C: Closed")).toBeTruthy();

    // column_semantics composite diff
    expect(screen.getByText("semantic_type")).toBeTruthy();
    expect(screen.getByText("currency")).toBeTruthy();
    expect(screen.getByText("USD")).toBeTruthy();

    // Target chips: Object badge + clickable column buttons
    expect(screen.getAllByText(en["catalog.history.targetObject"])).toHaveLength(2);
    const statusBtn = screen.getByRole("button", { name: "status" });
    fireEvent.click(statusBtn);
    expect(onOpenColumn).toHaveBeenCalledWith("col-1");

    const amountBtn = screen.getByRole("button", { name: "amount" });
    fireEvent.click(amountBtn);
    expect(onOpenColumn).toHaveBeenCalledWith("col-2");

    // Actor provenance
    expect(screen.getAllByText("Alice")).toHaveLength(2);
    expect(screen.getByText("Catalog Agent")).toBeTruthy();
  });

  it("passes server-side filters to listSemanticsChanges and clears filters", async () => {
    mount();
    await screen.findByText("Customer Orders");

    // Scope filter -> column
    fireEvent.click(screen.getByRole("combobox", { name: en["catalog.history.scope"] }));
    fireEvent.click(await screen.findByRole("option", { name: en["catalog.history.scopeColumn"] }));
    await waitFor(() =>
      expect(api.listChanges).toHaveBeenLastCalledWith(
        "obj-1",
        expect.objectContaining({ scope: "column" }),
      ),
    );

    // Column filter -> status
    fireEvent.click(screen.getByRole("combobox", { name: en["catalog.history.columnFilter"] }));
    fireEvent.click(await screen.findByRole("option", { name: "status (Order Status)" }));
    await waitFor(() =>
      expect(api.listChanges).toHaveBeenLastCalledWith(
        "obj-1",
        expect.objectContaining({ scope: "column", column_id: "col-1" }),
      ),
    );

    // Source filter -> MCP
    fireEvent.click(screen.getByRole("combobox", { name: en["catalog.history.sourceFilter"] }));
    fireEvent.click(await screen.findByRole("option", { name: "MCP" }));
    await waitFor(() =>
      expect(api.listChanges).toHaveBeenLastCalledWith(
        "obj-1",
        expect.objectContaining({
          scope: "column",
          column_id: "col-1",
          semantic_source: "mcp",
        }),
      ),
    );

    // Empty filtered result shows noMatch message
    api.listChanges.mockResolvedValueOnce({ items: [], total: 0, limit: 50, offset: 0 });
    fireEvent.click(screen.getByRole("combobox", { name: en["catalog.history.fieldFilter"] }));
    fireEvent.click(
      await screen.findByRole("option", { name: en["catalog.semantics.businessName"] }),
    );
    expect(await screen.findByText(en["catalog.history.noMatch"])).toBeTruthy();

    // Clear filters resets all params
    api.listChanges.mockResolvedValueOnce({
      items: changes,
      total: changes.length,
      limit: 50,
      offset: 0,
    });
    const clearButtons = screen.getAllByRole("button", { name: en["common.filters.clear"] });
    fireEvent.click(clearButtons[0]);
    await waitFor(() =>
      expect(api.listChanges).toHaveBeenLastCalledWith("obj-1", {
        limit: 50,
        offset: 0,
        scope: undefined,
        column_id: undefined,
        field_name: undefined,
        semantic_source: undefined,
      }),
    );
  });
});
