/** @vitest-environment jsdom */
import { MantineProvider } from "@mantine/core";
import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { createElement, type ReactNode } from "react";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { ApiError } from "@/lib/api";
import { leavePromptOpen, settleLeavePrompt } from "@/components/navigation/leaveGuard";
import en from "@/locales/en-US/common.json";
import type { CatalogObject, CatalogJoin } from "@/features/sources/types";
import { JoinsTab } from "./JoinsTab";

const api = vi.hoisted(() => ({ search: vi.fn(), get: vi.fn(), list: vi.fn(), create: vi.fn(), patch: vi.fn(), reject: vi.fn(), restore: vi.fn(), delete: vi.fn(), path: vi.fn() }));
const notice = vi.hoisted(() => vi.fn());
const feedback = vi.hoisted(() => vi.fn());
vi.mock("@/providers/notification-provider", () => ({ presentConsoleNotification: feedback, dismissConsoleNotification: vi.fn() }));
vi.mock("@refinedev/core", () => ({ useTranslate: () => (key: string, options?: Record<string, unknown>) => ((en as Record<string, string>)[key] ?? key).replace(/\{\{(\w+)\}\}/g, (_, name: string) => String(options?.[name] ?? "")), useNotification: () => ({ open: notice }) }));
vi.mock("@/features/sources/api/catalog", () => ({ searchCatalogObjects: api.search, getCatalogObject: api.get }));
vi.mock("@/features/sources/api/joins", () => ({ listObjectJoins: api.list, createJoin: api.create, patchJoin: api.patch, deleteJoin: api.delete, rejectJoin: api.reject, restoreJoin: api.restore, getJoinPath: api.path }));
vi.mock("@/components/navigation/ConsoleLink", () => ({ ConsoleLink: ({ children, href }: { children: ReactNode; href: string }) => createElement("a", { href }, children) }));

export const object: CatalogObject = {
  id: "orders", name: "orders", schema_name: "public", source_id: "source", locator_key: "obj/pg/demo/public/table/orders", object_type: "table", business_name: null, business_description: null, ddl: null, is_present: true, collected_at: null,
  columns: [
    { id: "id", name: "id", locator_key: "col/pg/demo/public/table/orders/column/id", data_type: "int", nullable: false, business_name: null, business_description: null, ordinal: 1, is_present: true },
    { id: "parent", name: "parent_id", locator_key: "col/pg/demo/public/table/orders/column/parent_id", data_type: "int", nullable: true, business_name: null, business_description: null, ordinal: 2, is_present: true },
    { id: "absent", name: "removed", locator_key: "col/pg/demo/public/table/orders/column/removed", data_type: "int", nullable: true, business_name: null, business_description: null, ordinal: 3, is_present: false },
  ],
};
const incoming: CatalogJoin = { id: "edge", from_column_id: "remote", to_column_id: "id", from_column_locator_key: "col/pg/other/public/table/lines/column/order_id", to_column_locator_key: object.columns[0].locator_key, evidence: "Verified mapping", join_kind: "LEFT", join_expression: "lines.order_id = orders.id", created_by_user_id: "actor", created_at: "2026-11-01T00:00:00Z" };
function mount(writable = true) { return render(createElement(MantineProvider, { env: "test" }, createElement(JoinsTab, { object, writable }))); }
beforeEach(() => {
  vi.clearAllMocks();
  api.search.mockResolvedValue({ items: [], truncated: false });
  api.list.mockResolvedValue({ items: [incoming], total: 1, limit: 50, offset: 0 });
  Object.defineProperty(window, "matchMedia", { value: (query: string) => ({ matches: false, media: query, addEventListener: vi.fn(), removeEventListener: vi.fn() }), configurable: true });
  globalThis.ResizeObserver = class { observe() {} unobserve() {} disconnect() {} };
  Element.prototype.scrollIntoView = vi.fn();
});
afterEach(cleanup);
it("browses stored incoming endpoints without authoring lookups or a permanent editor", async () => {
  mount(false);
  expect(await screen.findByText("lines.order_id")).toBeTruthy();
  expect(screen.getByText("orders.id")).toBeTruthy();
  expect(screen.getByText("Incoming")).toBeTruthy();
  expect(api.search).not.toHaveBeenCalled();
  expect(api.get).not.toHaveBeenCalled();
  expect(screen.queryByRole("textbox", { name: "Evidence" })).toBeNull();
  fireEvent.click(screen.getByRole("button", { name: "Inspect relation" }));
  expect(await screen.findByText(incoming.join_expression!)).toBeTruthy();
});
it("opens a bounded edit session with immutable incoming endpoints and preserves kind/expression on PATCH", async () => {
  mount();
  fireEvent.click(await screen.findByRole("button", { name: "Edit" }));
  expect(await screen.findByRole("dialog")).toBeTruthy();
  expect(screen.queryByRole("combobox", { name: "Current column" })).toBeNull();
  fireEvent.change(screen.getByRole("textbox", { name: "Evidence" }), { target: { value: "Updated evidence" } });
  fireEvent.click(screen.getByRole("button", { name: "Save relation" }));
  await waitFor(() => expect(api.patch).toHaveBeenCalledWith("edge", { evidence: "Updated evidence", join_kind: "LEFT", join_expression: "lines.order_id = orders.id" }));
  expect(api.get).not.toHaveBeenCalled();
  expect(api.search).not.toHaveBeenCalled();
  await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());
  await waitFor(() => expect(document.activeElement).toBe(screen.getByRole("button", { name: "Edit" })));
});

it("returns rejection cancellation to the real overflow opener", async () => {
  mount();
  const opener = await screen.findByRole("button", { name: /^More actions for/ });
  opener.focus();
  fireEvent.click(opener);
  const reject = await screen.findByRole("menuitem", { name: "Reject" });
  reject.focus();
  fireEvent.click(reject);
  const dialog = await screen.findByRole("dialog");
  fireEvent.click(within(dialog).getByRole("button", { name: "Cancel" }));
  await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());
  await waitFor(() => expect(document.activeElement).toBe(opener));
});

async function choose(label: string, option: string) {
  fireEvent.click(screen.getByRole("combobox", { name: label }));
  fireEvent.click(await screen.findByRole("option", { name: option }));
}

it("creates an explicitly incoming same-object pair with no implicit or absent column", async () => {
  mount();
  fireEvent.click(await screen.findByRole("button", { name: "Add relation" }));
  await screen.findByRole("dialog");
  const local = screen.getByRole("combobox", { name: "Current column" }) as HTMLInputElement;
  expect(local.value).toBe("");
  fireEvent.click(screen.getByRole("button", { name: "Create relation" }));
  expect(document.activeElement).toBe(local);
  expect(api.create).not.toHaveBeenCalled();
  fireEvent.click(local);
  expect(screen.queryByRole("option", { name: /removed/ })).toBeNull();
  fireEvent.click(screen.getByRole("option", { name: "id · int" }));
  await choose("Direction", "Incoming · other object → this object");
  await choose("Other object", "public.orders · obj/pg/demo/public/table/orders");
  await choose("Other column", "parent_id · int");
  fireEvent.change(screen.getByRole("textbox", { name: "Evidence" }), { target: { value: "Verified parent mapping" } });
  fireEvent.click(screen.getByRole("button", { name: "Create relation" }));
  await waitFor(() => expect(api.create).toHaveBeenCalledWith({ from_column_id: "parent", to_column_id: "id", evidence: "Verified parent mapping", join_kind: "INNER", join_expression: null }));
  expect(api.get).not.toHaveBeenCalled();
});

it("rejects identical columns, retains a refused draft and asks before dirty close", async () => {
  api.create.mockRejectedValue(new ApiError(409, "JOIN_ALREADY_DEFINED", "already exists", "req-pair"));
  mount();
  fireEvent.click(await screen.findByRole("button", { name: "Add relation" }));
  await choose("Current column", "id · int");
  await choose("Other object", "public.orders · obj/pg/demo/public/table/orders");
  await choose("Other column", "id · int");
  fireEvent.change(screen.getByRole("textbox", { name: "Evidence" }), { target: { value: "Keep this evidence" } });
  fireEvent.click(screen.getByRole("button", { name: "Create relation" }));
  expect(api.create).not.toHaveBeenCalled();
  expect(document.activeElement).toBe(screen.getByRole("combobox", { name: "Other column" }));
  await choose("Other column", "parent_id · int");
  fireEvent.click(screen.getByRole("button", { name: "Create relation" }));
  await waitFor(() => expect(api.create).toHaveBeenCalledTimes(1));
  expect((screen.getByRole("textbox", { name: "Evidence" }) as HTMLTextAreaElement).value).toBe("Keep this evidence");
  fireEvent.click(screen.getByRole("button", { name: "Cancel" }));
  await waitFor(() => expect(leavePromptOpen()).toBe(true));
  settleLeavePrompt(false);
  expect(screen.getByRole("dialog")).toBeTruthy();
});

it("does not offer stale columns when switching objects and ignores an older response", async () => {
  const first = { ...object, id: "first", name: "first", columns: [{ ...object.columns[0], id: "first-column", name: "first_column" }] };
  const second = { ...object, id: "second", name: "second", columns: [{ ...object.columns[0], id: "second-column", name: "second_column" }] };
  api.search.mockResolvedValue({ items: [first, second], truncated: true });
  let finishFirst!: (value: { object: CatalogObject }) => void;
  api.get.mockImplementation((id: string) => id === "first" ? new Promise((resolve) => { finishFirst = resolve; }) : Promise.resolve({ object: second }));
  mount();
  fireEvent.click(await screen.findByRole("button", { name: "Add relation" }));
  await screen.findByRole("dialog");
  fireEvent.change(screen.getByRole("textbox", { name: "Search objects" }), { target: { value: "candidate" } });
  await waitFor(() => expect(api.search).toHaveBeenCalled());
  await choose("Other object", "public.first · obj/pg/demo/public/table/orders");
  await waitFor(() => expect(api.get).toHaveBeenCalledWith("first"));
  expect(screen.queryByRole("combobox", { name: "Other column" })).toBeNull();
  await choose("Other object", "public.second · obj/pg/demo/public/table/orders");
  await waitFor(() => expect(screen.getByRole("combobox", { name: "Other column" })).toBeTruthy());
  finishFirst({ object: first });
  fireEvent.click(screen.getByRole("combobox", { name: "Other column" }));
  expect(await screen.findByRole("option", { name: "second_column · int" })).toBeTruthy();
  expect(screen.queryByRole("option", { name: "first_column · int" })).toBeNull();
});

it("invalidates a failed search notification retry when its query is replaced", async () => {
  api.search.mockRejectedValueOnce(new ApiError(503, "UNAVAILABLE", "Search unavailable"));
  api.search.mockResolvedValue({ items: [], truncated: false });
  mount();
  fireEvent.click(await screen.findByRole("button", { name: "Add relation" }));
  const search = await screen.findByRole("textbox", { name: "Search objects" });
  fireEvent.change(search, { target: { value: "first" } });
  await waitFor(() => expect(feedback).toHaveBeenCalled());
  const notification = render(createElement(MantineProvider, { env: "test" }, feedback.mock.calls.at(-1)![0].message));
  const retry = within(notification.container).getByRole("button", { name: "Retry" });
  fireEvent.change(search, { target: { value: "second" } });
  await waitFor(() => expect(api.search).toHaveBeenCalledWith("second", { limit: 20 }));
  fireEvent.click(retry);
  await new Promise((resolve) => setTimeout(resolve, 50));
  expect(api.search).toHaveBeenCalledTimes(2);
});

it("confirms durable rejection by stored pair with Cancel focused before making a request", async () => {
  mount();
  fireEvent.click(await screen.findByRole("button", { name: /^More actions for/ }));
  fireEvent.click(await screen.findByRole("menuitem", { name: "Reject" }));
  const dialog = await screen.findByRole("dialog");
  expect(dialog.textContent).toContain("lines.order_id → orders.id");
  expect(dialog.textContent).toContain("does not delete");
  expect(dialog.textContent).toContain("until explicitly restored");
  await waitFor(() => expect(document.activeElement).toBe(within(dialog).getByRole("button", { name: "Cancel" })));
  expect(api.reject).not.toHaveBeenCalled();
  fireEvent.click(within(dialog).getByRole("button", { name: "Reject" }));
  await waitFor(() => expect(api.reject).toHaveBeenCalledWith("edge"));
  await waitFor(() => expect(api.list).toHaveBeenCalledTimes(2));
});

it("opens path exploration immediately with parameters inside and retries a failed load", async () => {
  let fail!: (error: unknown) => void;
  api.path.mockImplementationOnce(() => new Promise((_, reject) => { fail = reject; }));
  api.path.mockResolvedValue({ paths: [], paths_found: 0, direct_joins: [] });
  mount(false);
  expect(screen.queryByLabelText("At most hops")).toBeNull();
  fireEvent.click(screen.getByRole("button", { name: "Explore paths" }));
  const drawer = await screen.findByRole("dialog");
  expect(within(drawer).getByLabelText("At most hops")).toBeTruthy();
  expect(within(drawer).getByRole("status").textContent).toContain("Loading paths");
  await waitFor(() => expect(api.path).toHaveBeenCalledWith({ start: "orders", max_hops: 2, top_targets: 10 }));
  fail(new ApiError(503, "JOIN_PATH_UNAVAILABLE", "Cannot expand", "req-path"));
  const retry = await within(drawer).findByRole("button", { name: /Retry/ });
  expect(within(drawer).queryByText("No paths found")).toBeNull();
  fireEvent.click(retry);
  expect(await within(drawer).findByText("No paths found")).toBeTruthy();
  expect(api.path).toHaveBeenCalledTimes(2);
});

it("keeps lifecycle policy separate from provenance and limits rows to two inline actions", async () => {
  const automatic = { ...incoming, id: "auto", created_by_user_id: null };
  const rejected = { ...incoming, id: "rejected", is_rejected: true };
  const rejectedAuto = { ...automatic, id: "rejected-auto", is_rejected: true };
  api.list.mockResolvedValue({ items: [incoming, automatic, rejected, rejectedAuto], total: 4, limit: 50, offset: 0 });
  mount();
  await screen.findAllByText("lines.order_id");
  const rows = screen.getAllByRole("row").slice(1);
  expect(within(rows[0]).getAllByRole("button")).toHaveLength(3);
  expect(within(rows[0]).queryByRole("button", { name: "Delete" })).toBeNull();
  for (const row of rows.slice(2)) {
    expect(within(row).getByRole("button", { name: "Restore" })).toBeTruthy();
    expect(within(row).queryByRole("button", { name: "Edit" })).toBeNull();
    expect(within(row).queryByRole("button", { name: /^More actions/ })).toBeNull();
  }
  expect(within(rows[2]).getByText("Manual")).toBeTruthy();
  expect(within(rows[3]).getByText("Automated")).toBeTruthy();
  fireEvent.click(within(rows[1]).getByRole("button", { name: /^More actions/ }));
  expect(await screen.findByRole("menuitem", { name: "Reject" })).toBeTruthy();
  expect(screen.queryByRole("menuitem", { name: "Delete" })).toBeNull();
});

it("keeps restore pending local to its row and ignores duplicate clicks", async () => {
  let finish!: () => void;
  api.restore.mockImplementationOnce(() => new Promise<void>((resolve) => { finish = resolve; }));
  api.list.mockResolvedValue({ items: [{ ...incoming, is_rejected: true }, { ...incoming, id: "other", is_rejected: true }], total: 2, limit: 50, offset: 0 });
  mount();
  const buttons = await screen.findAllByRole("button", { name: "Restore" });
  fireEvent.click(buttons[0]);
  fireEvent.click(buttons[0]);
  expect(api.restore).toHaveBeenCalledTimes(1);
  expect(buttons[0].getAttribute("data-loading")).not.toBeNull();
  expect(buttons[1].getAttribute("data-loading")).toBeNull();
  expect((buttons[1] as HTMLButtonElement).disabled).toBe(false);
  finish();
  await waitFor(() => expect(api.list).toHaveBeenCalledTimes(2));
});

it("names irreversible deletion, keeps confirmation after a refusal, and presents backend details", async () => {
  api.delete.mockRejectedValueOnce(new ApiError(403, "AUTH_FORBIDDEN", "Other Source refuses write", "req-delete"));
  mount();
  fireEvent.click(await screen.findByRole("button", { name: /^More actions/ }));
  fireEvent.click(await screen.findByRole("menuitem", { name: "Delete" }));
  const dialog = await screen.findByRole("dialog");
  expect(dialog.textContent).toContain("lines.order_id → orders.id");
  expect(dialog.textContent).toContain("irreversible");
  expect(dialog.textContent).toContain("automatic discovery may insert the pair again");
  await waitFor(() => expect(document.activeElement).toBe(within(dialog).getByRole("button", { name: "Cancel" })));
  fireEvent.click(within(dialog).getByRole("button", { name: "Delete" }));
  await waitFor(() => expect(api.delete).toHaveBeenCalledWith("edge"));
  await waitFor(() => expect(feedback).toHaveBeenCalled());
  const error = feedback.mock.calls.find(([value]) => value.type === "error")![0];
  expect(error.title).not.toContain("Other Source refuses write");
  expect(error.message.props.detail).toBe("Other Source refuses write");
  expect(error.message.props.requestId).toBe("req-delete");
  expect(screen.getByRole("dialog")).toBeTruthy();
  expect(api.list).toHaveBeenCalledTimes(1);
});

it("uses bounded path parameters and navigation while ignoring a response from a previous object", async () => {
  let finishOld!: (value: unknown) => void;
  api.path.mockImplementationOnce(() => new Promise((resolve) => { finishOld = resolve; }));
  api.path.mockResolvedValue({ paths_found: 1, direct_joins: [], paths: [{ target_object_id: "target", path_summary: "New path", hops: [{ join_id: "reverse", from_column_id: "local", to_column_id: "remote", join_kind: "LEFT" }] }] });
  const view = mount(false);
  fireEvent.click(screen.getByRole("button", { name: "Explore paths" }));
  await screen.findByRole("dialog");
  await waitFor(() => expect(api.path).toHaveBeenCalledTimes(1));
  view.rerender(createElement(MantineProvider, { env: "test" }, createElement(JoinsTab, { object: { ...object, id: "new-object" }, writable: false })));
  await screen.findByText("Path summary: New path");
  finishOld({ paths_found: 1, direct_joins: [], paths: [{ path_summary: "Stale path", hops: [] }] });
  await waitFor(() => expect(screen.queryByText("Path summary: Stale path")).toBeNull());
  expect(screen.getByText(/Arrows show path traversal/)).toBeTruthy();
  expect(screen.getByRole("link", { name: "Open target object" }).getAttribute("href")).toBe("/console/catalog/target");
  const drawer = screen.getByRole("dialog");
  fireEvent.change(within(drawer).getByLabelText("At most hops"), { target: { value: "5" } });
  fireEvent.click(within(drawer).getByRole("button", { name: "Explore paths" }));
  await waitFor(() => expect(api.path).toHaveBeenLastCalledWith({ start: "new-object", max_hops: 5, top_targets: 10 }));
  expect(api.search).not.toHaveBeenCalled();
});
