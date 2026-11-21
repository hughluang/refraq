/** @vitest-environment jsdom */

import { MantineProvider } from "@mantine/core";
import { notifications, notificationsStore } from "@mantine/notifications";
import { act, cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { createElement, type ReactNode } from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { ApiError } from "@/lib/api";
import en from "@/locales/en-US/common.json";
import { ConsoleNotifications } from "@/providers/notification-provider";

import { CatalogObjectDetail } from "./CatalogObjectDetail";

const getCatalogObject = vi.hoisted(() => vi.fn());
const openNotification = vi.hoisted(() => vi.fn());
const mirrorGrants = vi.hoisted(() => new Set<string>());

const copy = en as Record<string, string>;

function translate(key: string) {
  return copy[key] ?? key;
}

vi.mock("@refinedev/core", () => ({
  matchResourceFromRoute: () => ({ found: false }),
  useTranslate: () => translate,
  useNotification: () => ({ open: openNotification }),
  useCan: ({ resource, action }: { resource: string; action: string }) => ({
    data: { can: resource === "mirrors" && mirrorGrants.has(action) },
    isLoading: false,
  }),
  useBreadcrumb: () => ({ breadcrumbs: [] }),
}));

vi.mock("next/link", () => ({
  default: ({ href, children }: { href: string; children: ReactNode }) =>
    createElement("a", { href }, children),
  useLinkStatus: () => ({ pending: false }),
}));

vi.mock("next/navigation", () => ({
  usePathname: () => "/console/catalog/obj_1",
  useRouter: () => ({ push: vi.fn(), replace: vi.fn(), refresh: vi.fn() }),
  useSearchParams: () => new URLSearchParams(),
}));

vi.mock("@/features/branding/BrandingProvider", () => ({
  useBranding: () => ({ brandName: "Refraq" }),
}));

vi.mock("@/providers/session-store", () => ({
  useSessionStore: (selector: (state: { user: null }) => unknown) =>
    selector({ user: null }),
}));

vi.mock("@/features/sources/api/catalog", async () => {
  const actual = await vi.importActual<typeof import("@/features/sources/api/catalog")>(
    "@/features/sources/api/catalog",
  );
  return { ...actual, resolveCatalogObject: getCatalogObject };
});

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

const orders = {
  id: "obj_1", source_id: "source", schema_name: "public", name: "orders",
  object_type: "table", locator_key: "obj/postgresql/demo/public/table/orders",
  columns: [], is_present: true, mirror: { enabled: false, can_enable: true, can_disable: false, mirror_id: null },
};

function acceptedMirror() {
  return new Response(JSON.stringify({ mirror: { enabled: true, can_enable: false, can_disable: true, mirror_id: "mirror_1" }, operation_id: "op_1" }), { status: 200 });
}

function stubMirrorPut(post: (request: RequestInit) => Promise<Response>) {
  const submit = vi.fn(post);
  vi.stubGlobal("fetch", (path: string, request: RequestInit) =>
    path === "/api/objects/obj_1/mirror" && request.method === "PUT"
      ? submit(request)
      : Promise.resolve(new Response('{"items":[]}')),
  );
  return submit;
}

describe("CatalogObjectDetail load", () => {
  beforeEach(() => {
    stubDomApis();
    getCatalogObject.mockReset();
    mirrorGrants.clear();
    openNotification.mockReset();
    resetNotifications();
  });

  afterEach(() => {
    cleanup();
    resetNotifications();
    vi.unstubAllGlobals();
  });

  it("submits the resolved object id once and follows the accepted Mirror with read access", async () => {
    mirrorGrants.add("edit").add("show");
    getCatalogObject.mockResolvedValueOnce({ object: orders }).mockResolvedValue({
      object: { ...orders, mirror: { enabled: true, can_enable: false, can_disable: true, mirror_id: "mirror_1" } },
    });
    let finish!: (response: Response) => void;
    const submit = stubMirrorPut(() => new Promise<Response>((resolve) => { finish = resolve; }));
    render(shell(createElement(CatalogObjectDetail, { objectId: orders.locator_key })));

    const enable = await screen.findByRole("switch", { name: "Mirror synchronization" });
    act(() => {
      fireEvent.click(enable);
      fireEvent.click(enable);
    });
    expect(submit).toHaveBeenCalledTimes(1);
    expect(submit.mock.calls[0][0].body).toBe('{"enabled":true}');
    await act(async () => finish(acceptedMirror()));

    expect(openNotification).toHaveBeenCalledWith(expect.objectContaining({
      type: "success", message: "Mirror setting saved",
    }));
    const link = await screen.findByRole("link", { name: "View mirror" });
    expect(link.getAttribute("href")).toBe("/console/mirrors/mirror_1");
    expect(screen.getByRole("switch", { name: "Mirror synchronization", checked: true })).toBeTruthy();
  });

  it("uses independent read and write permissions for the Mirror controls", async () => {
    mirrorGrants.add("show");
    getCatalogObject.mockResolvedValue({
      object: { ...orders, mirror: { enabled: false, can_enable: true, can_disable: false, mirror_id: "mirror_1" } },
    });
    const record = () => shell(createElement(CatalogObjectDetail, { objectId: orders.id }));
    const view = render(record());
    expect(await screen.findByRole("link", { name: "View mirror" })).toBeTruthy();
    expect(screen.getByRole("switch", { name: "Mirror synchronization" }).hasAttribute("disabled")).toBe(true);

    mirrorGrants.clear();
    view.rerender(record());
    expect(screen.queryByRole("link", { name: "View mirror" })).toBeNull();
    expect(screen.queryByRole("switch", { name: "Mirror synchronization" })).toBeNull();

    mirrorGrants.add("edit");
    view.rerender(record());
    expect(screen.queryByRole("link", { name: "View mirror" })).toBeNull();
    expect(screen.getByRole("switch", { name: "Mirror synchronization" })).toBeTruthy();
  });

  it("withdraws the stale enable action and reports the problem when the server denies it", async () => {
    mirrorGrants.add("edit");
    getCatalogObject.mockResolvedValueOnce({ object: orders }).mockResolvedValue({
      object: { ...orders, mirror: null },
    });
    const submit = stubMirrorPut(async () => new Response(
      JSON.stringify({ code: "AUTH_FORBIDDEN", detail: "Forbidden" }),
      { status: 403 },
    ));
    render(shell(createElement(CatalogObjectDetail, { objectId: orders.id })));

    fireEvent.click(await screen.findByRole("switch", { name: "Mirror synchronization" }));
    expect(await screen.findByRole("alert")).toBeTruthy();
    expect(getCatalogObject).toHaveBeenCalledTimes(2);
    expect(submit).toHaveBeenCalledTimes(1);
    expect(openNotification).not.toHaveBeenCalled();
    expect(screen.queryByRole("switch", { name: "Mirror synchronization" })).toBeNull();
  });

  it("confirms turning off, then recovers the saved setting after a lost reply", async () => {
    mirrorGrants.add("edit");
    getCatalogObject.mockResolvedValueOnce({
      object: { ...orders, mirror: { enabled: true, can_enable: false, can_disable: true, mirror_id: null } },
    }).mockResolvedValue({ object: orders });
    const submit = stubMirrorPut(async () => { throw new TypeError("Connection closed"); });
    render(shell(createElement(CatalogObjectDetail, { objectId: orders.id })));
    const control = await screen.findByRole("switch", { checked: true });
    fireEvent.click(control);
    expect(submit).not.toHaveBeenCalled();
    fireEvent.click(await screen.findByRole("button", { name: "Cancel" }));
    expect(submit).not.toHaveBeenCalled();
    fireEvent.click(control);
    fireEvent.click(await screen.findByRole("button", { name: "Confirm" }));
    await screen.findByRole("switch", { checked: false });
    expect(submit).toHaveBeenCalledTimes(1);
    expect(submit.mock.calls[0][0].body).toBe('{"enabled":false}');
    expect(screen.queryByRole("link", { name: "View mirror" })).toBeNull();
    expect(await screen.findByRole("alert")).toBeTruthy();
  });

  it("keeps the pending enable request when the user tries to refresh", async () => {
    mirrorGrants.add("edit").add("show");
    getCatalogObject.mockResolvedValueOnce({ object: orders }).mockResolvedValue({
      object: { ...orders, mirror: { enabled: true, can_enable: false, can_disable: true, mirror_id: "mirror_1" } },
    });
    let finish!: (response: Response) => void;
    const submit = stubMirrorPut(() => new Promise<Response>((resolve) => { finish = resolve; }));
    render(shell(createElement(CatalogObjectDetail, { objectId: orders.id })));
    fireEvent.click(await screen.findByRole("switch", { name: "Mirror synchronization" }));
    const refresh = screen.getByRole("button", { name: "Refresh" });
    fireEvent.click(refresh);

    expect(refresh.hasAttribute("disabled")).toBe(true);
    expect(submit.mock.calls[0][0].signal?.aborted).toBe(false);
    expect(getCatalogObject).toHaveBeenCalledTimes(1);
    await act(async () => finish(acceptedMirror()));

    expect(await screen.findByRole("link", { name: "View mirror" })).toBeTruthy();
    expect(getCatalogObject).toHaveBeenCalledTimes(1);
  });

  it("ignores late Mirror acceptance after navigation", async () => {
    mirrorGrants.add("edit").add("show");
    getCatalogObject.mockResolvedValueOnce({ object: orders }).mockResolvedValue({
      object: { ...orders, mirror: null },
    });
    let finish!: (response: Response) => void;
    const submit = stubMirrorPut(() => new Promise<Response>((resolve) => { finish = resolve; }));
    const view = render(shell(createElement(CatalogObjectDetail, { objectId: orders.id })));
    fireEvent.click(await screen.findByRole("switch", { name: "Mirror synchronization" }));
    view.rerender(shell(createElement(CatalogObjectDetail, { objectId: "other_object" })));
    expect(submit.mock.calls[0][0].signal?.aborted).toBe(true);
    await act(async () => finish(acceptedMirror()));
    expect(getCatalogObject).toHaveBeenCalledTimes(2);
    expect(openNotification).not.toHaveBeenCalled();
    expect(screen.queryByRole("link", { name: "View mirror" })).toBeNull();
  });

  it("shows unloaded and one notice with the request id when the object fails to load", async () => {
    getCatalogObject.mockRejectedValue(
      new ApiError(500, "NO_SUCH_CODE", "database offline", "req-18"),
    );
    render(shell(createElement(CatalogObjectDetail, { objectId: "obj_1" })));

    const heading = await screen.findByRole("heading", { name: "Details" });
    expect(document.querySelector("[data-page-header]")?.contains(heading)).toBe(true);
    expect(screen.getByRole("button", { name: "Not loaded" })).toBeTruthy();
    expect(screen.queryByRole("heading", { name: "Page not found" })).toBeNull();
    expect(screen.queryByText("Something went wrong")).toBeNull();

    expect(await screen.findAllByRole("alert")).toHaveLength(1);
    fireEvent.click(screen.getByText("Details", { selector: "summary" }));
    expect(screen.getByText("database offline").closest("details")).toBeTruthy();
    expect(screen.getByText("Request ID: req-18").closest("details")).toBeTruthy();

    fireEvent.click(screen.getByRole("button", { name: "Retry" }));
    await waitFor(() => expect(getCatalogObject).toHaveBeenCalledTimes(2));
  });

  it("keeps supplementary object metadata available behind a compact disclosure", async () => {
    getCatalogObject.mockResolvedValue({ object: {
      id: "obj_1", source_id: "source", schema_name: "public", name: "orders",
      object_type: "table", locator_key: "obj/postgresql/demo/public/table/orders",
      columns: [], is_present: true, business_semantics_ready: false,
    } });
    render(shell(createElement(CatalogObjectDetail, { objectId: "obj_1" })));
    await screen.findByRole("heading", { name: "public.orders" });
    const locator = screen.getByText("obj/postgresql/demo/public/table/orders");
    const details = locator.closest("details")!;
    expect(details.open).toBe(false);
    expect(details.querySelector("summary")?.textContent).toContain("Present");
    fireEvent.click(details.querySelector("summary")!);
    expect(details.open).toBe(true);
    expect(screen.getByRole("button", { name: "Copy locator" })).toBeTruthy();
    expect(screen.getByRole("tablist").style.flexWrap).toBe("nowrap");
  });

  it("ignores a prior object's late response after navigation", async () => {
    let finish!: (value: unknown) => void;
    getCatalogObject.mockImplementationOnce(() => new Promise((resolve) => { finish = resolve; }));
    getCatalogObject.mockResolvedValue({ object: {
      id: "new", source_id: "source", schema_name: "public", name: "new",
      object_type: "table", locator_key: "obj/postgresql/demo/public/table/new",
      columns: [], is_present: true,
    } });
    const view = render(shell(createElement(CatalogObjectDetail, { objectId: "old" })));
    view.rerender(shell(createElement(CatalogObjectDetail, { objectId: "new" })));
    await screen.findByRole("heading", { name: "public.new" });
    expect(getCatalogObject.mock.calls[0][1].aborted).toBe(true);
    finish({ object: { id: "old", schema_name: "public", name: "old", columns: [] } });
    await waitFor(() => expect(screen.getByRole("heading", { name: "public.new" })).toBeTruthy());
    expect(screen.queryByRole("heading", { name: "public.old" })).toBeNull();
  });

  it("keeps a missing object on not-found", async () => {
    getCatalogObject.mockResolvedValue({ object: null });
    render(shell(createElement(CatalogObjectDetail, { objectId: "obj_missing" })));

    expect(await screen.findByRole("heading", { name: "Page not found" })).toBeTruthy();
    expect(screen.queryByRole("button", { name: "Not loaded" })).toBeNull();
    expect(screen.queryByRole("alert")).toBeNull();
    expect(getCatalogObject).toHaveBeenCalledTimes(1);
  });

  it("removes the table when refresh discovers revoked access", async () => {
    getCatalogObject.mockResolvedValueOnce({ object: {
      id: "obj_1", source_id: "source", schema_name: "public", name: "orders",
      object_type: "table", locator_key: "obj/postgresql/demo/public/table/orders",
      columns: [], is_present: true,
    } }).mockRejectedValueOnce(new ApiError(404, "CATALOG_OBJECT_NOT_FOUND", ""));
    render(shell(createElement(CatalogObjectDetail, { objectId: "obj_1" })));
    await screen.findByRole("heading", { name: "public.orders" });
    fireEvent.click(screen.getByRole("button", { name: copy["catalog.refresh"] }));
    await waitFor(() => expect(screen.queryByRole("heading", { name: "public.orders" })).toBeNull());
  });
});
