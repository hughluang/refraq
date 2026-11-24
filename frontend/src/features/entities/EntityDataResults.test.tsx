/** @vitest-environment jsdom */

import { MantineProvider } from "@mantine/core";
import { act, cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, expect, it, vi } from "vitest";

import { getDataRow } from "@/features/entities/accessApi";
import { EntityDataColumns, EntityDataResults } from "@/features/entities/EntityDataResults";
import type { DataSchema } from "@/features/entities/accessTypes";
import { ApiError } from "@/lib/api";
import { copyText } from "@/lib/copy-text";

vi.mock("@refinedev/core", () => ({ useTranslate: () => (key: string, values?: { field?: string }) => values?.field ? key + " " + values.field : key }));
vi.mock("@/features/entities/accessApi", () => ({ getDataRow: vi.fn() }));
vi.mock("@/lib/copy-text", () => ({ copyText: vi.fn() }));
vi.mock("@/providers/notification-provider", () => ({ presentConsoleNotification: vi.fn() }));

const schema: DataSchema = {
  entity: { name: "Orders", table_name: "orders", writable: false },
  business_key: "sku",
  attributes: [{ name: "private_note", type: "text" }, { name: "sku", type: "string" }, { name: "payload", type: "json" }],
  withheld_field: "__withheld",
};
const row = { row_id: 17, sku: "ORDER-17", private_note: null, payload: { qty: 2 }, __withheld: ["private_note"] };
const props = {
  schema, rows: [row], tableName: "orders", narrow: { narrow: { type: "role", id: "operator" } },
  list: { page: 1, setPage: vi.fn(), pageSize: 50, total: 1, reload: vi.fn(), presentation: { state: "ready" as const, refreshing: false } },
  sort: null, visibleFields: null, onPageSize: vi.fn(), onSort: vi.fn(), onDetailError: vi.fn(),
};

beforeEach(() => {
  Object.defineProperty(window, "matchMedia", { configurable: true, value: (media: string) => ({
    media, matches: false, addEventListener() {}, removeEventListener() {},
  }) });
  vi.stubGlobal("ResizeObserver", class { observe() {} unobserve() {} disconnect() {} });
});

afterEach(() => { cleanup(); vi.resetAllMocks(); vi.unstubAllGlobals(); });

it("leads with the business key, sorts scalars, and falls back to row_id after hiding the key", () => {
  const view = render(<MantineProvider env="test"><EntityDataResults {...props} /></MantineProvider>);
  expect(screen.getAllByRole("columnheader")[0].textContent).toBe("sku");
  fireEvent.click(screen.getByRole("button", { name: "sku" }));
  expect(props.onSort).toHaveBeenCalledWith({ field: "sku", direction: "asc" });
  expect(within(screen.getByRole("columnheader", { name: "payload" })).queryByRole("button")).toBeNull();
  expect(screen.getByText('{"qty":2}')).toBeTruthy();
  expect(screen.getByText("entities.access.cell.withheld")).toBeTruthy();
  view.rerender(<MantineProvider env="test"><EntityDataResults {...props} visibleFields={["payload"]} /></MantineProvider>);
  expect(screen.getByRole("button", { name: "17" })).toBeTruthy();
  expect(screen.getAllByRole("columnheader")[0].textContent).toBe("row_id");
});

it("reads the whole record with the active narrow and copies only the presented value", async () => {
  vi.mocked(getDataRow).mockResolvedValue({ row: { ...row, private_note: "unavailable fixture", new_private_field: "unavailable extra" } });
  render(<MantineProvider env="test"><EntityDataResults {...props} visibleFields={["sku"]} /></MantineProvider>);
  fireEvent.click(screen.getByRole("button", { name: "ORDER-17" }));
  const drawer = within(await screen.findByRole("dialog"));
  expect(await drawer.findByText("payload")).toBeTruthy();
  expect(getDataRow).toHaveBeenCalledWith("orders", { row_id: 17, ...props.narrow });
  expect(drawer.getByText("entities.access.cell.withheld")).toBeTruthy();
  expect(drawer.queryByText(/unavailable/)).toBeNull();
  expect(drawer.queryByRole("button", { name: /copyValue private_note/ })).toBeNull();
  fireEvent.click(drawer.getByRole("button", { name: /copyValue payload/ }));
  expect(copyText).toHaveBeenCalledWith(JSON.stringify(row.payload, null, 2));
});

it("discards a detail response after close and asks the list to invalidate access on a denied get", async () => {
  let release!: (value: { row: typeof row }) => void;
  vi.mocked(getDataRow).mockReturnValueOnce(new Promise((resolve) => { release = resolve; }))
    .mockRejectedValueOnce(new ApiError(403, "AUTH_FORBIDDEN", "denied"));
  render(<MantineProvider env="test"><EntityDataResults {...props} /></MantineProvider>);
  fireEvent.click(screen.getByRole("button", { name: "ORDER-17" }));
  fireEvent.click(screen.getByRole("button", { name: "form.dialog.close" }));
  await act(async () => { release({ row }); });
  expect(screen.queryByRole("dialog")).toBeNull();
  fireEvent.click(screen.getByRole("button", { name: "ORDER-17" }));
  await waitFor(() => expect(props.onDetailError).toHaveBeenCalledOnce());
  expect(screen.queryByRole("dialog")).toBeNull();
});

it("opens an exact BIGINT row and preserves integer tokens and named keys in its JSON", async () => {
  const rowId = BigInt("9223372036854775807");
  const payload = { toString: "literal property", nested: [BigInt("9007199254740993")] };
  const record = { ...row, row_id: rowId, payload };
  vi.mocked(getDataRow).mockResolvedValue({ row: record });
  render(<MantineProvider env="test"><EntityDataResults {...props} rows={[record]} visibleFields={["payload"]} /></MantineProvider>);
  expect(screen.getByText('{"toString":"literal property","nested":[9007199254740993]}')).toBeTruthy();
  fireEvent.click(screen.getByRole("button", { name: "9223372036854775807" }));
  const drawer = within(await screen.findByRole("dialog"));
  await drawer.findByText("payload");
  expect(getDataRow).toHaveBeenCalledWith("orders", { row_id: rowId, ...props.narrow });
  fireEvent.click(drawer.getByRole("button", { name: /copyValue payload/ }));
  expect(copyText).toHaveBeenCalledWith('{\n  "toString": "literal property",\n  "nested": [\n    9007199254740993\n  ]\n}');
});

it("changes visibility without modifying the schema", () => {
  const onChange = vi.fn();
  render(<MantineProvider env="test"><EntityDataColumns schema={schema} visibleFields={null} onChange={onChange} /></MantineProvider>);
  fireEvent.click(screen.getByRole("button", { name: "entities.data.grid.columns" }));
  fireEvent.click(screen.getByRole("checkbox", { name: "sku" }));
  expect(onChange).toHaveBeenCalledWith(["private_note", "payload"]);
  fireEvent.change(screen.getByRole("textbox", { name: "entities.data.grid.findColumn" }), { target: { value: "pay" } });
  expect(screen.getAllByRole("checkbox")).toHaveLength(1);
});
