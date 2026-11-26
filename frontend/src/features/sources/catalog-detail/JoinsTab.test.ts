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
const clipboard = vi.hoisted(() => ({ copyText: vi.fn() }));
const notice = vi.hoisted(() => vi.fn());
const feedback = vi.hoisted(() => vi.fn());
vi.mock("@/providers/notification-provider", () => ({ presentConsoleNotification: feedback, dismissConsoleNotification: vi.fn() }));
vi.mock("@refinedev/core", () => ({ useTranslate: () => (key: string, options?: Record<string, unknown>) => ((en as Record<string, string>)[key] ?? key).replace(/\{\{(\w+)\}\}/g, (_, name: string) => String(options?.[name] ?? "")), useNotification: () => ({ open: notice }) }));
vi.mock("@/features/sources/api/catalog", () => ({ searchCatalogObjects: api.search, getCatalogObject: api.get }));
vi.mock("@/features/sources/api/joins", () => ({ listObjectJoins: api.list, createJoin: api.create, patchJoin: api.patch, deleteJoin: api.delete, rejectJoin: api.reject, restoreJoin: api.restore, getJoinPath: api.path }));
vi.mock("@/components/navigation/ConsoleLink", () => ({ ConsoleLink: ({ children, href }: { children: ReactNode; href: string }) => createElement("a", { href }, children) }));
vi.mock("@/lib/copy-text", () => ({ copyText: clipboard.copyText }));

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
  clipboard.copyText.mockResolvedValue(undefined);
  api.search.mockResolvedValue({ items: [], truncated: false });
  api.list.mockResolvedValue({ items: [incoming], total: 1, limit: 50, offset: 0 });
  Object.defineProperty(window, "matchMedia", { value: (query: string) => ({ matches: false, media: query, addEventListener: vi.fn(), removeEventListener: vi.fn() }), configurable: true });
  globalThis.ResizeObserver = class { observe() {} unobserve() {} disconnect() {} };
  Object.defineProperty(window, "DOMMatrixReadOnly", { value: class { m22 = 1; }, configurable: true });
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
  const detail = await screen.findByRole("region", { name: "Relation details" });
  expect(within(detail).getByText(incoming.join_expression!)).toBeTruthy();
  expect(within(detail).queryByRole("button", { name: "Edit" })).toBeNull();
  expect(within(detail).queryByRole("button", { name: /^More actions/ })).toBeNull();
  expect(within(detail).queryByRole("textbox")).toBeNull();
  expect(screen.queryByRole("dialog")).toBeNull();
});
it("opens a bounded edit session with immutable incoming endpoints and preserves kind/expression on PATCH", async () => {
  mount();
  fireEvent.click(await screen.findByRole("button", { name: "Edit" }));
  expect(await screen.findByRole("region", { name: "Editing join" })).toBeTruthy();
  expect(screen.queryByRole("dialog")).toBeNull();
  expect(screen.queryByRole("combobox", { name: "Current column" })).toBeNull();
  fireEvent.change(screen.getByRole("textbox", { name: "Evidence" }), { target: { value: "Updated evidence" } });
  fireEvent.click(screen.getByRole("button", { name: "Save relation" }));
  await waitFor(() => expect(api.patch).toHaveBeenCalledWith("edge", { evidence: "Updated evidence", join_kind: "LEFT", join_expression: "lines.order_id = orders.id" }));
  expect(api.get).not.toHaveBeenCalled();
  expect(api.search).not.toHaveBeenCalled();
  await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());
  expect(await screen.findByRole("region", { name: "Relation details" })).toBeTruthy();
  expect(screen.queryByRole("textbox", { name: "Evidence" })).toBeNull();
});

it("keeps the browser mounted and restores its keyboard opener after dirty edit cancellation returns to detail", async () => {
  mount();
  const index = await screen.findByRole("region", { name: "Relation index" });
  const graph = screen.getByRole("region", { name: "Relation graph", exact: true });
  const inspect = within(index).getByRole("button", { name: "Inspect relation" });
  vi.spyOn(inspect, "getClientRects").mockReturnValue([{}] as unknown as DOMRectList);
  inspect.focus();
  fireEvent.click(inspect);
  const detail = await screen.findByRole("region", { name: "Relation details" });
  expect(screen.queryByRole("dialog")).toBeNull();
  expect(index.isConnected).toBe(true);
  expect(graph.isConnected).toBe(true);
  expect(index.closest("[hidden]")).not.toBeNull();
  expect(screen.queryByRole("textbox", { name: "Search loaded relations" })).toBeNull();
  expect(screen.queryByRole("button", { name: "Add relation" })).toBeNull();
  expect(screen.queryByRole("button", { name: "Explore paths" })).toBeNull();
  const back = within(detail).getByRole("button", { name: "Back to graph and index" });
  expect(document.activeElement).toBe(back);
  fireEvent.keyDown(back, { key: "Escape" });
  fireEvent.submit(detail.querySelector("form")!);
  expect(api.patch).not.toHaveBeenCalled();
  expect(leavePromptOpen()).toBe(false);
  fireEvent.click(within(detail).getByRole("button", { name: "Edit" }));
  const kind = await screen.findByRole("combobox", { name: "Join kind" });
  await waitFor(() => expect(document.activeElement).toBe(kind));
  expect(screen.queryByRole("button", { name: "Back to graph and index" })).toBeNull();
  fireEvent.change(screen.getByRole("textbox", { name: "Evidence" }), { target: { value: "Discard this draft" } });
  fireEvent.click(screen.getByRole("button", { name: "Cancel" }));
  await waitFor(() => expect(leavePromptOpen()).toBe(true));
  settleLeavePrompt(false);
  expect(screen.getByRole("textbox", { name: "Evidence" })).toHaveProperty("value", "Discard this draft");
  fireEvent.click(screen.getByRole("button", { name: "Cancel" }));
  await waitFor(() => expect(leavePromptOpen()).toBe(true));
  settleLeavePrompt(true);
  const restored = await screen.findByRole("region", { name: "Relation details" });
  expect(within(restored).getByText("Verified mapping")).toBeTruthy();
  expect(within(restored).queryByText("Discard this draft")).toBeNull();
  fireEvent.click(within(restored).getByRole("button", { name: "Back to graph and index" }));
  await waitFor(() => expect(document.activeElement).toBe(inspect));
  expect(screen.getByRole("region", { name: "Relation index" })).toBe(index);
  expect(screen.getByRole("region", { name: "Relation graph", exact: true })).toBe(graph);
  expect(within(index).getByRole("row", { selected: true })).toBeTruthy();
});

it.each(["Inspect relation", "Edit"])("restores the explicit %s opener even when another browser control was focused", async (label) => {
  mount();
  const opener = await screen.findByRole("button", { name: label, exact: true });
  vi.spyOn(opener, "getClientRects").mockReturnValue([{}] as unknown as DOMRectList);
  const search = screen.getByRole("textbox", { name: "Search loaded relations" });
  search.focus();
  expect(document.activeElement).not.toBe(opener);
  fireEvent.click(opener);
  if (label === "Edit") fireEvent.click(await screen.findByRole("button", { name: "Cancel", exact: true }));
  fireEvent.click(await screen.findByRole("button", { name: "Back to graph and index" }));
  await waitFor(() => expect(document.activeElement).toBe(opener));
});

it.each(["removed", "hidden", "unfocusable"])("falls back to index search when the explicit opener is %s", async (state) => {
  mount();
  const opener = await screen.findByRole("button", { name: "Inspect relation" });
  vi.spyOn(opener, "getClientRects").mockReturnValue([{}] as unknown as DOMRectList);
  fireEvent.click(opener);
  await screen.findByRole("region", { name: "Relation details" });
  if (state === "removed") opener.remove();
  else if (state === "hidden") opener.hidden = true;
  else vi.spyOn(opener, "focus").mockImplementation(() => {});
  fireEvent.click(screen.getByRole("button", { name: "Back to graph and index" }));
  await waitFor(() => expect(document.activeElement).toBe(screen.getByRole("textbox", { name: "Search loaded relations" })));
});

it("exposes immutable endpoint validation refusals as form errors rather than hidden edit fields", async () => {
  api.patch.mockRejectedValueOnce(new ApiError(422, "REQUEST_INVALID", "Endpoint no longer usable", null, {}, [{ field: "body.from_column_id", message: "Column is absent" }]));
  mount();
  fireEvent.click(await screen.findByRole("button", { name: "Edit" }));
  fireEvent.change(screen.getByRole("textbox", { name: "Evidence" }), { target: { value: "Retained evidence" } });
  fireEvent.click(screen.getByRole("button", { name: "Save relation" }));
  expect(await screen.findByRole("alert")).toBeTruthy();
  expect(feedback).toHaveBeenCalled();
  expect((screen.getByRole("textbox", { name: "Evidence" }) as HTMLTextAreaElement).value).toBe("Retained evidence");
});

it("clears a missing saved relation and falls back to index search focus", async () => {
  mount();
  fireEvent.click(await screen.findByRole("button", { name: "Edit" }));
  api.list.mockResolvedValue({ items: [], total: 0, limit: 50, offset: 0 });
  fireEvent.click(screen.getByRole("button", { name: "Save relation" }));
  await waitFor(() => expect(screen.queryByRole("region", { name: "Editing join" })).toBeNull());
  await waitFor(() => expect(document.activeElement).toBe(screen.getByRole("textbox", { name: "Search loaded relations" })));
  expect(screen.queryByRole("region", { name: "Relation details" })).toBeNull();
  expect(screen.queryByRole("row", { selected: true })).toBeNull();
});

it.each([false, true])("shows rejected detail without editable controls (writable: %s)", async (writable) => {
  api.list.mockResolvedValue({ items: [{ ...incoming, is_rejected: true }], total: 1, limit: 50, offset: 0 });
  mount(writable);
  fireEvent.click(await screen.findByRole("button", { name: "Inspect relation" }));
  const detail = await screen.findByRole("region", { name: "Relation details" });
  expect(within(detail).getByText("Rejected")).toBeTruthy();
  expect(within(detail).getByText("Join kind")).toBeTruthy();
  expect(within(detail).getByText(incoming.join_expression!)).toBeTruthy();
  expect(within(detail).getByText(incoming.evidence)).toBeTruthy();
  expect(within(detail).getByRole("link", { name: "orders.id" }).getAttribute("href")).toContain("orders");
  expect(within(detail).queryByRole("textbox")).toBeNull();
  expect(within(detail).queryByRole("combobox")).toBeNull();
  expect(within(detail).queryByRole("button", { name: "Edit" })).toBeNull();
  expect(within(detail).queryByRole("button", { name: "Restore" }) !== null).toBe(writable);
  expect(screen.queryByRole("dialog")).toBeNull();
});

it("refreshes saved values in detail and starts the next edit with a clean baseline", async () => {
  mount();
  fireEvent.click(await screen.findByRole("button", { name: "Edit" }));
  fireEvent.change(screen.getByRole("textbox", { name: "Evidence" }), { target: { value: "Saved evidence" } });
  fireEvent.change(screen.getByRole("textbox", { name: "Join expression" }), { target: { value: "saved.expression" } });
  api.list.mockResolvedValue({ items: [{ ...incoming, evidence: "Saved evidence", join_expression: "saved.expression" }], total: 1, limit: 50, offset: 0 });
  fireEvent.click(screen.getByRole("button", { name: "Save relation" }));
  const detail = await screen.findByRole("region", { name: "Relation details" });
  expect(within(detail).getByText("Saved evidence")).toBeTruthy();
  expect(within(detail).getByText("saved.expression")).toBeTruthy();
  fireEvent.click(within(detail).getByRole("button", { name: "Edit" }));
  expect(screen.getByRole("textbox", { name: "Evidence" })).toHaveProperty("value", "Saved evidence");
  fireEvent.click(screen.getByRole("button", { name: "Cancel" }));
  await screen.findByRole("region", { name: "Relation details" });
  expect(leavePromptOpen()).toBe(false);
});

it("stays in refreshed detail across rejection and restore, then exits after deletion", async () => {
  mount();
  fireEvent.click(await screen.findByRole("button", { name: "Inspect relation" }));
  let detail = await screen.findByRole("region", { name: "Relation details" });
  fireEvent.click(within(detail).getByRole("button", { name: "Reject", exact: true }));
  api.list.mockResolvedValue({ items: [{ ...incoming, is_rejected: true }], total: 1, limit: 50, offset: 0 });
  fireEvent.click(within(await screen.findByRole("dialog")).getByRole("button", { name: "Reject" }));
  await waitFor(() => expect(api.reject).toHaveBeenCalledWith("edge"));
  expect(await within(detail).findByText("Rejected")).toBeTruthy();
  expect(within(detail).queryByRole("button", { name: "Edit" })).toBeNull();
  api.list.mockResolvedValue({ items: [incoming], total: 1, limit: 50, offset: 0 });
  fireEvent.click(within(detail).getByRole("button", { name: "Restore" }));
  await waitFor(() => expect(api.restore).toHaveBeenCalledWith("edge"));
  await within(detail).findByRole("button", { name: "Edit" });
  expect(within(detail).queryByText("Rejected")).toBeNull();
  detail = screen.getByRole("region", { name: "Relation details" });
  fireEvent.click(within(detail).getByRole("button", { name: /^More actions/ }));
  fireEvent.click(await screen.findByRole("menuitem", { name: "Delete" }));
  api.list.mockResolvedValue({ items: [], total: 0, limit: 50, offset: 0 });
  fireEvent.click(within(await screen.findByRole("dialog")).getByRole("button", { name: "Delete" }));
  await waitFor(() => expect(api.delete).toHaveBeenCalledWith("edge"));
  await waitFor(() => expect(screen.queryByRole("region", { name: "Relation details" })).toBeNull());
  expect(document.activeElement).toBe(screen.getByRole("textbox", { name: "Search loaded relations" }));
  expect(screen.queryByRole("row", { selected: true })).toBeNull();
});

it("uses selected graph columns only as an explicit new draft prefill", async () => {
  mount();
  const graph = await screen.findByRole("region", { name: "Relation graph", exact: true });
  const column = (await within(graph).findByText("id", { selector: "button span" })).closest("button")!;
  fireEvent.click(column);
  expect(api.create).not.toHaveBeenCalled();
  fireEvent.click(screen.getByRole("button", { name: "Add relation" }));
  expect((screen.getByRole("combobox", { name: "Current column" }) as HTMLInputElement).value).toBe("id · int");
  expect(api.search).not.toHaveBeenCalled();
});

it("previews and swaps a draft's exact ordered columns without writing until Save", async () => {
  mount();
  fireEvent.click(await screen.findByRole("button", { name: "Add relation" }));
  expect(screen.queryByRole("dialog")).toBeNull();
  await choose("Current column", "id · int");
  await choose("Other object", "public.orders · obj/pg/demo/public/table/orders");
  await choose("Other column", "parent_id · int");
  expect(screen.getByText("Draft: orders.id → orders.parent_id")).toBeTruthy();
  fireEvent.click(screen.getByRole("button", { name: "Swap draft direction" }));
  expect(screen.getByText("Draft: orders.parent_id → orders.id")).toBeTruthy();
  expect(api.create).not.toHaveBeenCalled();
  fireEvent.keyDown(screen.getByRole("textbox", { name: "Evidence" }), { key: "Escape" });
  await waitFor(() => expect(leavePromptOpen()).toBe(true));
  settleLeavePrompt(false);
  expect(screen.getByText("Draft: orders.parent_id → orders.id")).toBeTruthy();
});

it("preserves custom kind and null expression while ignoring repeated amendment submits", async () => {
  let finish!: () => void;
  api.list.mockResolvedValue({ items: [{ ...incoming, join_kind: "CUSTOM", join_expression: null }], total: 1, limit: 50, offset: 0 });
  api.patch.mockImplementationOnce(() => new Promise<void>((resolve) => { finish = resolve; }));
  mount();
  fireEvent.click(await screen.findByRole("button", { name: "Edit" }));
  fireEvent.change(screen.getByRole("textbox", { name: "Evidence" }), { target: { value: "Custom evidence" } });
  const save = screen.getByRole("button", { name: "Save relation" });
  fireEvent.click(save);
  fireEvent.click(save);
  expect(api.patch).toHaveBeenCalledTimes(1);
  expect(api.patch).toHaveBeenCalledWith("edge", { evidence: "Custom evidence", join_kind: "CUSTOM", join_expression: null });
  finish();
  await waitFor(() => expect(screen.queryByRole("region", { name: "Editing join" })).toBeNull());
});

it("retains the local draft when an authorized search result refuses endpoint hydration", async () => {
  api.search.mockResolvedValue({ items: [{ ...object, id: "refused", name: "refused" }], truncated: false });
  api.get.mockRejectedValue(new ApiError(403, "AUTH_FORBIDDEN", "Read refused"));
  mount();
  fireEvent.click(await screen.findByRole("button", { name: "Add relation" }));
  await choose("Current column", "parent_id · int");
  searchObjects("refused");
  await waitFor(() => expect(api.search).toHaveBeenCalled());
  await choose("Other object", "public.refused · obj/pg/demo/public/table/orders");
  await waitFor(() => expect(feedback).toHaveBeenCalled());
  expect(screen.queryByRole("combobox", { name: "Other column" })).toBeNull();
  expect((screen.getByRole("combobox", { name: "Current column" }) as HTMLInputElement).value).toBe("parent_id · int");
  fireEvent.click(screen.getByRole("button", { name: "Create relation" }));
  expect(api.create).not.toHaveBeenCalled();
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

function searchObjects(value: string) {
  const input = screen.getByRole("combobox", { name: "Other object" });
  input.focus();
  fireEvent.change(input, { target: { value } });
}

async function choose(label: string, option: string) {
  fireEvent.click(screen.getByRole("combobox", { name: label }));
  fireEvent.click(await screen.findByRole("option", { name: option }));
}

it("creates an explicitly incoming same-object pair with no implicit or absent column", async () => {
  mount();
  fireEvent.click(await screen.findByRole("button", { name: "Add relation" }));
  await screen.findByRole("region", { name: "Add relation" });
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
  expect(await screen.findByRole("alert")).toHaveProperty("textContent", en["problems.unknown"]);
  expect(screen.getByRole("textbox", { name: "Evidence" }).getAttribute("aria-invalid")).not.toBe("true");
  expect((screen.getByRole("textbox", { name: "Evidence" }) as HTMLTextAreaElement).value).toBe("Keep this evidence");
  fireEvent.click(screen.getByRole("button", { name: "Cancel" }));
  await waitFor(() => expect(leavePromptOpen()).toBe(true));
  settleLeavePrompt(false);
  expect(screen.getByRole("region", { name: "Add relation" })).toBeTruthy();
});

it("does not offer stale columns when switching objects and ignores an older response", async () => {
  const first = { ...object, id: "first", name: "first", columns: [{ ...object.columns[0], id: "first-column", name: "first_column" }] };
  const second = { ...object, id: "second", name: "second", columns: [{ ...object.columns[0], id: "second-column", name: "second_column" }] };
  api.search.mockResolvedValue({ items: [first, second], truncated: true });
  let finishFirst!: (value: { object: CatalogObject }) => void;
  api.get.mockImplementation((id: string) => id === "first" ? new Promise((resolve) => { finishFirst = resolve; }) : Promise.resolve({ object: second }));
  mount();
  fireEvent.click(await screen.findByRole("button", { name: "Add relation" }));
  await screen.findByRole("region", { name: "Add relation" });
  searchObjects("candidate");
  await waitFor(() => expect(api.search).toHaveBeenCalled());
  await choose("Other object", "public.first · obj/pg/demo/public/table/orders");
  await waitFor(() => expect(api.get).toHaveBeenCalledWith("first"));
  expect(screen.queryByRole("combobox", { name: "Other column" })).toBeNull();
  searchObjects("candidate");
  await waitFor(() => expect(api.search).toHaveBeenCalledTimes(2));
  await choose("Other object", "public.second · obj/pg/demo/public/table/orders");
  await waitFor(() => expect(screen.getByRole("combobox", { name: "Other column" })).toBeTruthy());
  finishFirst({ object: first });
  fireEvent.click(screen.getByRole("combobox", { name: "Other column" }));
  expect(await screen.findByRole("option", { name: "second_column · int" })).toBeTruthy();
  expect(screen.queryByRole("option", { name: "first_column · int" })).toBeNull();
});

it("searches names and locators in the object selector, restores labels on close and clears endpoints", async () => {
  const remote = { ...object, id: "remote-object", name: "customers", locator_key: "obj/pg/other/public/table/customers" };
  const label = "public.customers · obj/pg/other/public/table/customers";
  api.search.mockResolvedValue({ items: [remote], truncated: true });
  api.get.mockResolvedValue({ object: remote });
  mount();
  fireEvent.click(await screen.findByRole("button", { name: "Add relation" }));
  const search = screen.getByRole("combobox", { name: "Other object" });
  expect(screen.queryByRole("textbox", { name: "Search objects" })).toBeNull();
  expect(search.getAttribute("placeholder")).toBe("Search by name or locator");
  fireEvent.click(search);
  expect(screen.getByRole("option", { name: "public.orders · obj/pg/demo/public/table/orders" })).toBeTruthy();
  expect(api.search).not.toHaveBeenCalled();
  searchObjects("customer");
  searchObjects("customers");
  expect(api.search).not.toHaveBeenCalled();
  await waitFor(() => expect(api.search).toHaveBeenCalledWith("customers", { limit: 20 }));
  expect(api.search).toHaveBeenCalledTimes(1);
  expect(screen.getByText(en["catalog.joins.searchTruncated"])).toBeTruthy();
  fireEvent.click(screen.getByRole("option", { name: label }));
  await screen.findByRole("combobox", { name: "Other column" });
  await choose("Other column", "parent_id · int");
  expect(search).toHaveProperty("value", label);
  await new Promise((resolve) => setTimeout(resolve, 350));
  expect(api.search).toHaveBeenCalledTimes(1);
  searchObjects(remote.locator_key);
  await waitFor(() => expect(api.search).toHaveBeenCalledWith(remote.locator_key, { limit: 20 }));
  fireEvent.blur(search);
  expect(search).toHaveProperty("value", label);
  expect(screen.getByRole("combobox", { name: "Other column" })).toHaveProperty("value", "parent_id · int");
  fireEvent.click(search);
  expect(screen.getByRole("option", { name: label })).toBeTruthy();
  const clear = search.closest(".mantine-Input-wrapper")!.querySelector("button")!;
  fireEvent.click(clear);
  expect(search).toHaveProperty("value", "");
  expect(screen.queryByRole("combobox", { name: "Other column" })).toBeNull();
  fireEvent.click(search);
  expect(screen.getByRole("option", { name: "public.orders · obj/pg/demo/public/table/orders" })).toBeTruthy();
  expect(screen.queryByRole("option", { name: label })).toBeNull();
  searchObjects("unfinished");
  fireEvent.blur(search);
  expect(search).toHaveProperty("value", "");
  await new Promise((resolve) => setTimeout(resolve, 350));
  expect(api.search).toHaveBeenCalledTimes(2);
});

it("ignores old search responses and keeps ranked semantic matches without local filtering", async () => {
  const remote = { ...object, id: "semantic", name: "customers" };
  let finishOld!: (value: unknown) => void;
  api.search.mockImplementationOnce(() => new Promise((resolve) => { finishOld = resolve; }));
  api.search.mockResolvedValue({ items: [remote], truncated: false });
  mount();
  fireEvent.click(await screen.findByRole("button", { name: "Add relation" }));
  searchObjects("old");
  await waitFor(() => expect(api.search).toHaveBeenCalledTimes(1));
  searchObjects("account owners");
  await waitFor(() => expect(api.search).toHaveBeenCalledTimes(2));
  expect(await screen.findByRole("option", { name: "public.customers · obj/pg/demo/public/table/orders" })).toBeTruthy();
  finishOld({ items: [{ ...object, id: "stale", name: "stale" }], truncated: true });
  await waitFor(() => expect(screen.queryByRole("option", { name: /public.stale/ })).toBeNull());
  searchObjects("");
  expect(screen.queryByRole("option", { name: /public.customers/ })).toBeNull();
  await new Promise((resolve) => setTimeout(resolve, 350));
  expect(api.search).toHaveBeenCalledTimes(2);
});

it("retries a failed object search without changing its query", async () => {
  api.search.mockRejectedValueOnce(new ApiError(503, "UNAVAILABLE", "Search unavailable"));
  api.search.mockResolvedValue({ items: [], truncated: false });
  mount();
  fireEvent.click(await screen.findByRole("button", { name: "Add relation" }));
  searchObjects("retry-name");
  fireEvent.click(await screen.findByRole("button", { name: "Retry" }));
  await waitFor(() => expect(api.search).toHaveBeenCalledTimes(2));
  expect(api.search).toHaveBeenLastCalledWith("retry-name", { limit: 20 });
});

it("invalidates a failed search notification retry when its query is replaced", async () => {
  api.search.mockRejectedValueOnce(new ApiError(503, "UNAVAILABLE", "Search unavailable"));
  api.search.mockResolvedValue({ items: [], truncated: false });
  mount();
  fireEvent.click(await screen.findByRole("button", { name: "Add relation" }));
  await screen.findByRole("combobox", { name: "Other object" });
  searchObjects("first");
  await waitFor(() => expect(feedback).toHaveBeenCalled());
  const notification = render(createElement(MantineProvider, { env: "test" }, feedback.mock.calls.at(-1)![0].message));
  const retry = within(notification.container).getByRole("button", { name: "Retry" });
  searchObjects("second");
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
  const drawer = await screen.findByRole("region", { name: "Join paths" });
  expect(screen.queryByRole("dialog")).toBeNull();
  expect(within(drawer).getByLabelText("At most hops")).toBeTruthy();
  expect(within(drawer).getByRole("status").textContent).toContain("Loading paths");
  await waitFor(() => expect(api.path).toHaveBeenCalledWith({ start: "orders", max_hops: 2, top_targets: 10 }));
  fail(new ApiError(503, "JOIN_PATH_UNAVAILABLE", "Cannot expand", "req-path"));
  const retry = await within(drawer).findByRole("button", { name: /Retry/ });
  expect(within(drawer).queryByText("No paths found")).toBeNull();
  fireEvent.click(retry);
  expect(await within(drawer).findByText(en["catalog.joins.path.empty"])).toBeTruthy();
  expect(api.path).toHaveBeenCalledTimes(2);
});

it("focuses path bounds on entry and returns keyboard focus to the neighborhood opener", async () => {
  api.path.mockResolvedValue({ paths: [], paths_found: 0, direct_joins: [] });
  mount(false);
  const explore = screen.getByRole("button", { name: "Explore paths" });
  explore.focus();
  fireEvent.click(explore);
  const paths = await screen.findByRole("region", { name: "Join paths" });
  await waitFor(() => expect(document.activeElement).toBe(within(paths).getByLabelText("At most hops")));
  fireEvent.click(within(paths).getByRole("button", { name: "Back to neighborhood" }));
  await waitFor(() => expect(document.activeElement).toBe(screen.getByRole("button", { name: "Explore paths" })));
});

it("selects read-only routes with exact traversal evidence and discards them before authoring mutations", async () => {
  api.path.mockResolvedValue({ paths_found: 2, direct_joins: [], paths: [
    { path_summary: "First route", hops: [{ join_id: "edge", from_column_id: "id", to_column_id: "remote", join_kind: "LEFT", evidence: "First evidence", join_expression: "unchanged LEFT expression" }] },
    { path_summary: "Second route", hops: [{ join_id: "unknown", from_column_id: "remote", to_column_id: "parent", join_kind: "RIGHT", evidence: "Second evidence", join_expression: "unchanged RIGHT expression" }] },
  ] });
  mount();
  await screen.findByText("lines.order_id");
  fireEvent.click(screen.getByRole("button", { name: "Explore paths" }));
  const paths = await screen.findByRole("region", { name: "Join paths" });
  expect(await within(paths).findByText("Evidence: First evidence")).toBeTruthy();
  fireEvent.click(within(paths).getByRole("button", { name: "2. Path summary: Second route" }));
  expect(within(paths).getByText("Traversal 1: remote → parent")).toBeTruthy();
  expect(within(paths).getByText("Reported join kind (stored meaning): RIGHT")).toBeTruthy();
  expect(within(paths).getByText("Join expression: unchanged RIGHT expression")).toBeTruthy();
  expect(within(paths).queryByText("Evidence: First evidence")).toBeNull();
  expect(within(paths).queryByRole("button", { name: "Edit" })).toBeNull();
  const routeGraph = within(paths).getByRole("region", { name: "Relation graph", exact: true });
  expect(within(routeGraph).getAllByRole("button").map((button) => button.textContent)).toEqual(["Fit"]);
  expect(within(paths).getByRole("button", { name: "Relation graph", pressed: true })).toBeTruthy();
  fireEvent.click(within(paths).getByRole("button", { name: "Join paths", exact: true }));
  expect(within(paths).getByRole("button", { name: "Join paths", exact: true, pressed: true })).toBeTruthy();
  expect(api.get).not.toHaveBeenCalled();
  fireEvent.click(screen.getByRole("button", { name: "Add relation" }));
  expect(screen.queryByRole("region", { name: "Join paths" })).toBeNull();
  fireEvent.click(screen.getByRole("button", { name: "Cancel" }));
  fireEvent.click(await screen.findByRole("button", { name: "Edit" }));
  fireEvent.click(screen.getByRole("button", { name: "Save relation" }));
  await waitFor(() => expect(api.list).toHaveBeenCalledTimes(2));
  await screen.findByRole("region", { name: "Relation details" });
  fireEvent.click(screen.getByRole("button", { name: "Back to graph and index" }));
  fireEvent.click(screen.getByRole("button", { name: "Explore paths" }));
  await waitFor(() => expect(api.path).toHaveBeenCalledTimes(2));
  expect(await screen.findByRole("button", { name: "1. Path summary: First route", pressed: true })).toBeTruthy();
});

it("invalidates path notification retries after replacement bounds and after exit", async () => {
  api.path.mockRejectedValueOnce(new ApiError(503, "UNAVAILABLE", "Path unavailable"));
  api.path.mockResolvedValue({ paths: [], paths_found: 0, direct_joins: [] });
  mount(false);
  fireEvent.click(screen.getByRole("button", { name: "Explore paths" }));
  await waitFor(() => expect(feedback).toHaveBeenCalled());
  const notification = render(createElement(MantineProvider, { env: "test" }, feedback.mock.calls.at(-1)![0].message));
  const retry = within(notification.container).getByRole("button", { name: "Retry" });
  const paths = screen.getByRole("region", { name: "Join paths" });
  fireEvent.change(within(paths).getByLabelText("At most hops"), { target: { value: "3" } });
  fireEvent.click(within(paths).getByRole("button", { name: "Explore paths" }));
  await within(paths).findByText(en["catalog.joins.path.empty"]);
  fireEvent.click(retry);
  expect(api.path).toHaveBeenCalledTimes(2);
  fireEvent.click(within(paths).getByRole("button", { name: "Back to neighborhood" }));
  fireEvent.click(retry);
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
  await screen.findByRole("region", { name: "Join paths" });
  await waitFor(() => expect(api.path).toHaveBeenCalledTimes(1));
  view.rerender(createElement(MantineProvider, { env: "test" }, createElement(JoinsTab, { object: { ...object, id: "new-object" }, writable: false })));
  expect(screen.queryByRole("region", { name: "Join paths" })).toBeNull();
  fireEvent.click(screen.getByRole("button", { name: "Explore paths" }));
  await screen.findByRole("button", { name: "1. Path summary: New path" });
  finishOld({ paths_found: 1, direct_joins: [], paths: [{ path_summary: "Stale path", hops: [] }] });
  await waitFor(() => expect(screen.queryByText("Path summary: Stale path")).toBeNull());
  expect(screen.getByText(/Hop arrows below show traversal/)).toBeTruthy();
  expect(screen.getByRole("link", { name: "Open target object" }).getAttribute("href")).toBe("/console/catalog/target");
  const drawer = screen.getByRole("region", { name: "Join paths" });
  fireEvent.change(within(drawer).getByLabelText("At most hops"), { target: { value: "5" } });
  fireEvent.click(within(drawer).getByRole("button", { name: "Explore paths" }));
  await waitFor(() => expect(api.path).toHaveBeenLastCalledWith({ start: "new-object", max_hops: 5, top_targets: 10 }));
  expect(api.search).not.toHaveBeenCalled();
});

it("selects a relation from the keyboard index and searches only loaded relations", async () => {
  mount(false);
  const index = await screen.findByRole("region", { name: "Relation index" });
  const inspect = within(index).getByRole("button", { name: "Inspect relation" });
  inspect.focus();
  fireEvent.keyDown(inspect, { key: "Enter" });
  fireEvent.click(inspect);
  expect(await screen.findByText("Verified mapping")).toBeTruthy();
  fireEvent.click(screen.getByRole("button", { name: "Back to graph and index" }));
  await waitFor(() => expect(document.activeElement).toBe(screen.getByRole("textbox", { name: "Search loaded relations" })));
  fireEvent.change(screen.getByRole("textbox", { name: "Search loaded relations" }), { target: { value: "not-loaded" } });
  expect(within(index).queryByText("lines.order_id")).toBeNull();
  expect(screen.getByText(/1 loaded of 1/)).toBeTruthy();
  expect(api.list).toHaveBeenCalledTimes(1);
  expect(api.get).not.toHaveBeenCalled();
});

it("pages the graph neighborhood explicitly without fetching remote details", async () => {
  api.list.mockImplementation((_: string, query: { offset: number }) => Promise.resolve({ items: query.offset === 0 ? [incoming] : [{ ...incoming, id: "next", evidence: "Second page" }], total: 51, limit: 50, offset: query.offset }));
  mount(false);
  await screen.findByText(/1 loaded of 51/);
  fireEvent.click(screen.getByRole("button", { name: "2", exact: true }));
  await waitFor(() => expect(api.list).toHaveBeenLastCalledWith("orders", { limit: 50, offset: 50 }));
  expect(await screen.findByText(/page 2/)).toBeTruthy();
  fireEvent.click(screen.getByRole("button", { name: "Inspect relation" }));
  expect(await screen.findByText("Second page")).toBeTruthy();
  fireEvent.click(screen.getByRole("button", { name: "Back to graph and index" }));
  expect(screen.getByText(/page 2/)).toBeTruthy();
  expect(screen.getByRole("row", { selected: true })).toBeTruthy();
  expect(api.list).toHaveBeenCalledTimes(2);
  expect(api.get).not.toHaveBeenCalled();
});

it("does not render a loaded graph before the relation tab is enabled", async () => {
  render(createElement(MantineProvider, { env: "test" }, createElement(JoinsTab, { object, writable: false, listEnabled: false })));
  await waitFor(() => expect(api.list).not.toHaveBeenCalled());
  expect(screen.queryByRole("region", { name: "Relation graph", exact: true })).toBeNull();
  expect(screen.queryByText(/0 loaded of 0/)).toBeNull();
});

it("does not show the previous object's neighborhood when the new object's read fails", async () => {
  const view = mount(false);
  await screen.findByText("lines.order_id");
  api.list.mockRejectedValueOnce(new ApiError(503, "UNAVAILABLE", "Unavailable"));
  view.rerender(createElement(MantineProvider, { env: "test" }, createElement(JoinsTab, { object: { ...object, id: "new-object", locator_key: "obj/pg/demo/public/table/new_object" }, writable: false })));
  await waitFor(() => expect(api.list).toHaveBeenLastCalledWith("new-object", { limit: 50, offset: 0 }));
  await screen.findByRole("button", { name: en["status.unloaded"] });
  expect(screen.queryByText("lines.order_id")).toBeNull();
  expect(screen.queryByRole("region", { name: "Relation graph", exact: true })).toBeNull();
});

it("labels retained relations with their loaded page after a page request fails", async () => {
  api.list.mockResolvedValueOnce({ items: [incoming], total: 51, limit: 50, offset: 0 });
  api.list.mockRejectedValueOnce(new ApiError(503, "UNAVAILABLE", "Unavailable"));
  mount(false);
  await screen.findByText(/1 loaded of 51/);
  fireEvent.click(screen.getByRole("button", { name: "2", exact: true }));
  await waitFor(() => expect(feedback).toHaveBeenCalled());
  expect(screen.getByText(/1 loaded of 51.*page 1/)).toBeTruthy();
  expect(screen.getByText("lines.order_id")).toBeTruthy();
});

it("keeps a failed relation read distinct from empty and allows retry", async () => {
  api.list.mockRejectedValueOnce(new ApiError(503, "UNAVAILABLE", "Unavailable"));
  mount(false);
  const retry = await screen.findByRole("button", { name: en["status.unloaded"] });
  expect(screen.queryByRole("region", { name: "Relation graph", exact: true })).toBeNull();
  expect(screen.queryByText(/0 loaded of 0/)).toBeNull();
  expect(screen.queryByText(en["catalog.joins.empty"])).toBeNull();
  fireEvent.click(retry);
  expect(await screen.findByText("lines.order_id")).toBeTruthy();
});

it("filters loaded relations by direction, state, and origin", async () => {
  const outgoingAuto: CatalogJoin = {
    id: "edge-out",
    from_column_id: "id",
    to_column_id: "cust-id",
    from_column_locator_key: object.columns[0].locator_key,
    to_column_locator_key: "col/pg/other/public/table/customers/column/id",
    evidence: "Outgoing auto",
    join_kind: "INNER",
    join_expression: "orders.id = customers.id",
    created_by_user_id: null,
    created_at: "2026-11-01T00:00:00Z",
    is_rejected: false,
  };
  const sameRejected: CatalogJoin = {
    id: "edge-same",
    from_column_id: "id",
    to_column_id: "parent",
    from_column_locator_key: object.columns[0].locator_key,
    to_column_locator_key: object.columns[1].locator_key,
    evidence: "Self rejected",
    join_kind: "LEFT",
    join_expression: "orders.id = orders.parent_id",
    created_by_user_id: "actor",
    created_at: "2026-11-01T00:00:00Z",
    is_rejected: true,
  };
  api.list.mockResolvedValue({ items: [incoming, outgoingAuto, sameRejected], total: 3, limit: 50, offset: 0 });
  mount(false);
  const index = await screen.findByRole("region", { name: "Relation index" });
  expect(within(index).getAllByRole("row").slice(1)).toHaveLength(3);

  fireEvent.click(within(index).getByRole("combobox", { name: en["catalog.joins.filterDirection"] }));
  fireEvent.click(await screen.findByRole("option", { name: `${en["catalog.joins.filterDirection"]}: ${en["catalog.joins.outgoing"]}` }));
  expect(within(index).getAllByRole("row").slice(1)).toHaveLength(1);
  expect(within(index).getByText("customers.id")).toBeTruthy();

  fireEvent.click(within(index).getByRole("combobox", { name: en["catalog.joins.filterDirection"] }));
  fireEvent.click(await screen.findByRole("option", { name: `${en["catalog.joins.filterDirection"]}: ${en["catalog.joins.filterAll"]}` }));
  expect(within(index).getAllByRole("row").slice(1)).toHaveLength(3);

  fireEvent.click(within(index).getByRole("combobox", { name: en["catalog.joins.filterStatus"] }));
  fireEvent.click(await screen.findByRole("option", { name: `${en["catalog.joins.filterStatus"]}: ${en["catalog.joins.state.rejected"]}` }));
  expect(within(index).getAllByRole("row").slice(1)).toHaveLength(1);
  expect(within(index).getByText("orders.parent_id")).toBeTruthy();

  fireEvent.click(within(index).getByRole("combobox", { name: en["catalog.joins.filterProvenance"] }));
  fireEvent.click(await screen.findByRole("option", { name: `${en["catalog.joins.filterProvenance"]}: ${en["catalog.joins.state.automated"]}` }));
  expect(within(index).getByText(en["common.noMatch"])).toBeTruthy();

  fireEvent.click(within(index).getByRole("button", { name: en["common.filters.clear"] }));
  expect(within(index).getAllByRole("row").slice(1)).toHaveLength(3);
});

it("supports target object, question, and copyable SQL skeleton in path exploration", async () => {
  const customers = { ...object, id: "cust-obj", name: "customers", locator_key: "obj/pg/demo/public/table/customers" };
  api.search.mockResolvedValue({ items: [customers], truncated: false });
  api.path.mockResolvedValue({
    paths_found: 1,
    direct_joins: [],
    paths: [
      {
        target_object_id: "cust-obj",
        path_summary: "orders → customers",
        hops: [
          {
            join_id: "edge-out",
            from_column_id: "id",
            to_column_id: "cust-id",
            from_column_locator_key: object.columns[0].locator_key,
            to_column_locator_key: "col/pg/demo/public/table/customers/column/id",
            join_kind: "LEFT",
            join_expression: "orders.id = customers.id",
            evidence: "FK match",
          },
        ],
      },
    ],
  });
  mount(false);
  fireEvent.click(screen.getByRole("button", { name: "Explore paths" }));
  const paths = await screen.findByRole("region", { name: "Join paths" });

  expect(await within(paths).findByText(en["catalog.joins.path.sqlPreview"])).toBeTruthy();
  expect(within(paths).getByText(/LEFT JOIN public\.customers ON orders\.id = customers\.id/)).toBeTruthy();

  fireEvent.click(within(paths).getByRole("button", { name: en["catalog.joins.path.copySql"] }));
  await waitFor(() =>
    expect(clipboard.copyText).toHaveBeenCalledWith(
      "SELECT *\nFROM public.orders\nLEFT JOIN public.customers ON orders.id = customers.id",
    ),
  );
  expect(notice).toHaveBeenLastCalledWith({
    type: "success",
    message: en["common.copy.success"],
  });

  const targetInput = within(paths).getByRole("combobox", { name: en["catalog.joins.path.targetObject"] });
  targetInput.focus();
  fireEvent.change(targetInput, { target: { value: "customers" } });
  await waitFor(() =>
    expect(api.search).toHaveBeenCalledWith("customers", { source_id: "source", limit: 20 }),
  );
  fireEvent.click(await screen.findByRole("option", { name: "public.customers · obj/pg/demo/public/table/customers" }));

  const questionInput = within(paths).getByRole("textbox", { name: en["catalog.joins.path.question"] });
  fireEvent.change(questionInput, { target: { value: "customer revenue" } });

  fireEvent.click(within(paths).getByRole("button", { name: "Explore paths" }));
  await waitFor(() =>
    expect(api.path).toHaveBeenLastCalledWith({
      start: "orders",
      max_hops: 2,
      top_targets: 10,
      target: "cust-obj",
      q: "customer revenue",
    }),
  );
});
