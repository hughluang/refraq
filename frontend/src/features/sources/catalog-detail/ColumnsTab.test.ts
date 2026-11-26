/** @vitest-environment jsdom */

import { MantineProvider } from "@mantine/core";
import { notifications, notificationsStore } from "@mantine/notifications";
import {
  cleanup,
  fireEvent,
  render,
  screen,
  waitFor,
} from "@testing-library/react";
import { createElement, type ReactNode } from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { ColumnsTab } from "@/features/sources/catalog-detail/ColumnsTab";
import { parseBulkEnumText } from "@/features/sources/catalog-detail/columnDrafts";
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

const semanticsApi = vi.hoisted(() => ({
  patchBatch: vi.fn(),
}));

function translate(key: string, options?: Record<string, unknown>) {
  const template = copy[key] ?? key;
  if (!options) return template;
  return template.replace(/\{\{(\w+)\}\}/g, (_, name: string) =>
    String(options[name] ?? ""),
  );
}

vi.mock("@refinedev/core", () => ({
  useTranslate: () => translate,
  useNotification: () => ({ open: vi.fn() }),
}));

vi.mock("next/link", () => ({
  default: ({
    href,
    children,
    ...props
  }: {
    href: string;
    children: ReactNode;
    [key: string]: unknown;
  }) => createElement("a", { href, ...props }, children),
  useLinkStatus: () => ({ pending: false }),
}));

vi.mock("next/navigation", () => ({
  usePathname: () => window.location.pathname,
  useRouter: () => ({ push: vi.fn(), replace: vi.fn(), refresh: vi.fn() }),
  useSearchParams: () => new URLSearchParams(window.location.search),
}));

vi.mock("@/features/sources/api/semantics", () => ({
  patchColumnSemanticsBatch: (...args: unknown[]) =>
    semanticsApi.patchBatch(...args),
}));

vi.mock("@/lib/pagination", async () => {
  const actual =
    await vi.importActual<typeof import("@/lib/pagination")>("@/lib/pagination");
  pageApi.real = actual.offsetPageFromItems;
  return {
    ...actual,
    offsetPageFromItems: (items: readonly unknown[], query: PageQuery) => {
      if (pageApi.fail) {
        throw new ApiError(
          500,
          "NO_SUCH_CODE",
          "columns unavailable",
          "req-columns",
        );
      }
      const real = pageApi.real;
      if (!real) throw new Error("missing page adapter");
      return real(items, query);
    },
  };
});

function column(overrides: Partial<CatalogColumn> = {}): CatalogColumn {
  return {
    id: "col-amount",
    locator_key: "public.orders.amount",
    name: "amount",
    data_type: "numeric",
    normalized_type: "decimal",
    nullable: true,
    business_name: null,
    business_description: null,
    ordinal: 1,
    is_present: true,
    ...overrides,
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

const WORKBENCH_OBJECT: CatalogObject = {
  ...OBJECT,
  primary_key: ["order_id"],
  foreign_keys: [
    {
      name: "fk_orders_customer",
      columns: ["customer_id"],
      ref_schema: "public",
      ref_table: "customers",
      ref_columns: ["id"],
      is_present: true,
      ref_object_id: "obj-customers",
    },
  ],
  indexes: [
    {
      name: "idx_orders_customer",
      columns: ["customer_id"],
      is_unique: false,
      is_present: true,
    },
  ],
  columns: [
    column({
      id: "col-order-id",
      locator_key: "public.orders.order_id",
      name: "order_id",
      data_type: "bigint",
      normalized_type: "integer",
      nullable: false,
      ordinal: 1,
      comment: "Primary order identifier",
      business_name: "Order ID",
      business_description: "Unique order key",
    }),
    column({
      id: "col-customer-id",
      locator_key: "public.orders.customer_id",
      name: "customer_id",
      data_type: "uuid",
      normalized_type: "unknown",
      nullable: false,
      ordinal: 2,
      comment: "Customer reference from CRM",
      business_name: null,
      business_description: null,
    }),
    column({
      id: "col-status",
      locator_key: "public.orders.status",
      name: "status",
      data_type: "varchar(32)",
      normalized_type: "string",
      nullable: false,
      ordinal: 3,
      comment: "Lifecycle state",
      business_name: "Order Status",
      business_description: "Current fulfillment status",
      enum_catalog: [{ code: "NEW", label: "New" }],
    }),
  ],
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

function renderColumns(
  props: Partial<Parameters<typeof ColumnsTab>[0]> = {},
) {
  return render(
    shell(
      createElement(ColumnsTab, {
        object: OBJECT,
        writable: false,
        onSaved: () => {},
        reloadEpoch: 0,
        ...props,
      }),
    ),
  );
}

describe("ColumnsTab load", () => {
  beforeEach(() => {
    stubDomApis();
    pageApi.fail = false;
    semanticsApi.patchBatch.mockReset();
    resetNotifications();
  });

  afterEach(() => {
    cleanup();
    resetNotifications();
  });

  it("shows unloaded and one error notification when the column list fails to load", async () => {
    pageApi.fail = true;
    renderColumns();

    const status = await screen.findByRole("button", {
      name: copy["status.unloaded"],
    });
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
    expect(
      screen.queryByRole("button", { name: copy["status.unloaded"] }),
    ).toBeNull();
  });

  it("keeps loaded columns and sends one notification when a later load fails", async () => {
    renderColumns();
    expect(await screen.findByText("amount")).toBeTruthy();
    expect(screen.queryByRole("alert")).toBeNull();

    pageApi.fail = true;
    fireEvent.change(
      screen.getByRole("textbox", { name: copy["catalog.columns.search"] }),
      {
        target: { value: "zzz" },
      },
    );

    expect(await screen.findByText("amount")).toBeTruthy();
    expect(
      screen.queryByRole("button", { name: copy["status.unloaded"] }),
    ).toBeNull();
    const alerts = screen.getAllByRole("alert");
    expect(alerts).toHaveLength(1);
    expect(alerts[0]?.textContent).toContain(copy["problems.unknown"]);
    expect(
      screen.getByRole("button", { name: copy["common.retry"] }),
    ).toBeTruthy();
  });
});

describe("ColumnsTab workbench", () => {
  beforeEach(() => {
    stubDomApis();
    pageApi.fail = false;
    semanticsApi.patchBatch.mockReset();
    resetNotifications();
  });

  afterEach(() => {
    cleanup();
    resetNotifications();
  });

  it("filters by search and clears filters", async () => {
    renderColumns({ object: WORKBENCH_OBJECT, writable: false });

    expect(await screen.findByText("order_id")).toBeTruthy();
    expect(screen.getByText("customer_id")).toBeTruthy();
    expect(screen.getByText("status")).toBeTruthy();

    // Unknown normalized type surfaces the type mappings link.
    expect(
      screen.getByRole("link", {
        name: copy["catalog.columns.typeMappingsLink"],
      }),
    ).toBeTruthy();

    // Search by DB comment
    fireEvent.change(
      screen.getByRole("textbox", { name: copy["catalog.columns.search"] }),
      { target: { value: "CRM" } },
    );

    await waitFor(() => {
      expect(screen.queryByText("order_id")).toBeNull();
      expect(screen.getByText("customer_id")).toBeTruthy();
    });

    const clearBtn = screen.getByRole("button", {
      name: copy["catalog.columns.clearFilters"],
    });
    fireEvent.click(clearBtn);

    expect(await screen.findByText("order_id")).toBeTruthy();
    expect(screen.getByText("customer_id")).toBeTruthy();
    expect(screen.getByText("status")).toBeTruthy();
  });

  it("supports inline editing and batch saving dirty columns", async () => {
    const onSaved = vi.fn();
    const updatedObject: CatalogObject = {
      ...WORKBENCH_OBJECT,
      columns: WORKBENCH_OBJECT.columns.map((c) =>
        c.id === "col-customer-id"
          ? { ...c, business_name: "Customer ID" }
          : c,
      ),
    };
    semanticsApi.patchBatch.mockResolvedValue({
      object: updatedObject,
      updated_count: 1,
      requested_count: 1,
      skipped_columns: [],
    });

    renderColumns({
      object: WORKBENCH_OBJECT,
      writable: true,
      onSaved,
    });

    const nameInput = await screen.findByRole("textbox", {
      name: `customer_id ${copy["catalog.semantics.businessName"]}`,
    });
    fireEvent.change(nameInput, { target: { value: "Customer ID" } });

    const saveBtn = await screen.findByRole("button", {
      name: translate("catalog.columns.saveDirty", { count: 1 }),
    });
    fireEvent.click(saveBtn);

    await waitFor(() => {
      expect(semanticsApi.patchBatch).toHaveBeenCalledWith("obj-1", [
        expect.objectContaining({
          column_name: "customer_id",
          business_name: "Customer ID",
        }),
      ]);
      expect(onSaved).toHaveBeenCalledWith(updatedObject);
    });
  });

  it("opens ColumnInspector, steps Next/Previous, and applies DB comment", async () => {
    renderColumns({
      object: WORKBENCH_OBJECT,
      writable: true,
    });

    const inspectButtons = await screen.findAllByRole("button", {
      name: copy["catalog.columns.inspect"],
    });
    expect(inspectButtons).toHaveLength(3);

    // Inspect first column (order_id)
    fireEvent.click(inspectButtons[0]!);
    expect(
      screen.getByRole("button", { name: copy["catalog.columns.prevColumn"] }),
    ).toHaveProperty("disabled", true);

    // Step Next -> customer_id
    fireEvent.click(
      screen.getByRole("button", { name: copy["catalog.columns.nextColumn"] }),
    );

    const useCommentBtn = await screen.findByRole("button", {
      name: copy["catalog.columns.useComment"],
    });
    fireEvent.click(useCommentBtn);

    // Dirty bar appears with 1 change
    expect(
      await screen.findByRole("button", {
        name: translate("catalog.columns.saveDirty", { count: 1 }),
      }),
    ).toBeTruthy();

    // Step Previous -> back to order_id
    fireEvent.click(
      screen.getByRole("button", { name: copy["catalog.columns.prevColumn"] }),
    );
    expect(
      screen.getByRole("button", { name: copy["catalog.columns.prevColumn"] }),
    ).toHaveProperty("disabled", true);
  });
});

describe("parseBulkEnumText", () => {
  it("parses TSV, colon-separated, and bare lines", () => {
    const entries = parseBulkEnumText(
      [
        "NEW\tNew order\tInitial state",
        "PAID: Paid in full",
        "CANCELLED",
        "",
      ].join("\n"),
    );

    expect(entries).toEqual([
      { code: "NEW", label: "New order", description: "Initial state" },
      { code: "PAID", label: "Paid in full", description: "" },
      { code: "CANCELLED", label: "CANCELLED", description: "" },
    ]);
  });
});
