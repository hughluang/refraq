/** @vitest-environment jsdom */

import { MantineProvider } from "@mantine/core";
import { notifications, notificationsStore } from "@mantine/notifications";
import { act, cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { createElement, type ReactNode } from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { ApiError } from "@/lib/api";
import en from "@/locales/en-US/common.json";
import { ConsoleNotifications } from "@/providers/notification-provider";

import { MirrorTableDrawer } from "@/features/mirrors/MirrorTableDrawer";
import { CatalogObjectDetail } from "./CatalogObjectDetail";

const listMirrorTables = vi.hoisted(() => vi.fn());
const getCatalogObject = vi.hoisted(() => vi.fn());
const openNotification = vi.hoisted(() => vi.fn());
const mirrorGrants = vi.hoisted(() => new Set<string>());

const copy = en as Record<string, string>;

function translate(key: string, options?: Record<string, unknown>) {
  const template = copy[key] ?? key;
  if (!options) return template;
  return template.replace(/\{\{(\w+)\}\}/g, (_, name: string) =>
    String(options[name] ?? ""),
  );
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
  usePathname: () => window.location.pathname,
  useRouter: () => ({ push: vi.fn(), replace: vi.fn(), refresh: vi.fn() }),
  useSearchParams: () => new URLSearchParams(window.location.search),
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
  return { ...actual, resolveCatalogObject: getCatalogObject, listMirrorTables };
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

const table = {
  object_id: orders.id, source_id: "source", source_key: "orders", source_name: "Orders DB",
  qualified_table: "public.orders", storage_destination: "source_mirror", source_size_bytes: 8192,
  estimated_rows: 23, mirror: orders.mirror, snapshot_holder: null,
};

async function openTableSetting() {
  fireEvent.click(await screen.findByRole("button", { name: "Mirror synchronization" }));
  return screen.findByRole("switch", { name: "Mirror synchronization" });
}

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
    window.history.replaceState(null, "", "/console/catalog/obj_1");
    listMirrorTables.mockReset().mockResolvedValue({ items: [table] });
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

  it("retries the selected Catalog table when its first read fails", async () => {
    mirrorGrants.add("edit");
    listMirrorTables.mockRejectedValueOnce(new ApiError(503, "UNAVAILABLE", "Catalog offline", "req-19"));
    render(shell(createElement(MirrorTableDrawer, { objectId: orders.id })));
    fireEvent.click(screen.getByRole("button", { name: "Mirror synchronization" }));
    expect(await screen.findByRole("button", { name: copy["status.unloaded"] })).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: copy["common.retry"] }));
    expect(await screen.findByRole("switch", { name: "Mirror synchronization" })).toBeTruthy();
    expect(listMirrorTables).toHaveBeenCalledTimes(2);
  });

  it("ignores a recovered read's Retry notification while a save is pending", async () => {
    mirrorGrants.add("edit");
    listMirrorTables.mockRejectedValueOnce(new ApiError(503, "UNAVAILABLE", "Catalog offline"));
    let finish!: (response: Response) => void;
    const submit = stubMirrorPut(() => new Promise(resolve => { finish = resolve; }));
    render(shell(createElement(MirrorTableDrawer, { objectId: orders.id })));
    fireEvent.click(screen.getByRole("button", { name: "Mirror synchronization" }));
    const oldRetry = await screen.findByRole("button", { name: copy["common.retry"] });
    fireEvent.click(screen.getByRole("button", { name: copy["status.unloaded"] }));
    fireEvent.click(await screen.findByRole("switch", { name: "Mirror synchronization" }));
    fireEvent.click(oldRetry);
    expect(listMirrorTables).toHaveBeenCalledTimes(2);
    expect(submit.mock.calls[0][0].signal?.aborted).toBe(false);

    await act(async () => finish(acceptedMirror()));
    expect(await screen.findByText("op_1")).toBeTruthy();
    expect(screen.getByRole("switch", { checked: true }).hasAttribute("disabled")).toBe(false);
  });

  it("withdraws the detail link and holder evidence when the management read returns forbidden", async () => {
    mirrorGrants.add("show");
    listMirrorTables.mockResolvedValue({ items: [{ ...table, mirror: { ...orders.mirror, mirror_id: "mirror_1" },
      snapshot_holder: { mirror_id: "holder", qualified_table: "public.shipment" } }] });
    vi.stubGlobal("fetch", async () => new Response('{"code":"AUTH_FORBIDDEN"}', { status: 403 }));
    render(shell(createElement(MirrorTableDrawer, { objectId: orders.id })));
    await openTableSetting();
    await screen.findByRole("alert");
    expect(screen.queryByRole("link", { name: "View mirror" })).toBeNull();
    expect(screen.queryByRole("link", { name: "public.shipment" })).toBeNull();
    expect(screen.queryByText(en["mirrors.copyAvailability"])).toBeNull();
  });

  it("submits the resolved object id once and follows the accepted Mirror with read access", async () => {
    mirrorGrants.add("edit").add("show");
    getCatalogObject.mockResolvedValueOnce({ object: orders }).mockResolvedValue({
      object: { ...orders, mirror: { enabled: true, can_enable: false, can_disable: true, mirror_id: "mirror_1" } },
    });
    let finish!: (response: Response) => void;
    const submit = stubMirrorPut(() => new Promise<Response>((resolve) => { finish = resolve; }));
    render(shell(createElement(CatalogObjectDetail, { objectId: orders.locator_key })));

    const enable = await openTableSetting();
    act(() => {
      fireEvent.click(enable);
      fireEvent.click(enable);
    });
    expect(submit).toHaveBeenCalledTimes(1);
    expect(submit.mock.calls[0][0].body).toBe('{"enabled":true}');
    await act(async () => finish(acceptedMirror()));

    expect(await screen.findByText("Request accepted")).toBeTruthy();
    expect(screen.getByText("op_1")).toBeTruthy();
    const link = await screen.findByRole("link", { name: "View mirror" });
    expect(link.getAttribute("href")).toBe("/console/mirrors/mirror_1?from=%2Fconsole%2Fcatalog%2Fobj_1%3FmirrorTable%3Dobj_1");
    expect(screen.getByRole("switch", { name: "Mirror synchronization", checked: true })).toBeTruthy();
  });

  it("uses independent read and write permissions for the Mirror controls", async () => {
    mirrorGrants.add("show");
    getCatalogObject.mockResolvedValue({
      object: { ...orders, mirror: { enabled: false, can_enable: true, can_disable: false, mirror_id: "mirror_1" } },
    });
    const record = () => shell(createElement(CatalogObjectDetail, { objectId: orders.id }));
    listMirrorTables.mockResolvedValue({ items: [{ ...table, mirror: { ...orders.mirror, mirror_id: "mirror_1" } }] });
    const view = render(record());
    await openTableSetting();
    expect(await screen.findByRole("link", { name: "View mirror" })).toBeTruthy();
    expect(screen.getByRole("switch", { name: "Mirror synchronization" }).hasAttribute("disabled")).toBe(true);

    mirrorGrants.clear();
    view.rerender(record());
    expect(screen.queryByRole("link", { name: "View mirror" })).toBeNull();
    expect(screen.queryByRole("switch", { name: "Mirror synchronization" })).toBeNull();

    mirrorGrants.add("edit");
    listMirrorTables.mockResolvedValue({ items: [table] });
    view.rerender(record());
    expect(screen.queryByRole("link", { name: "View mirror" })).toBeNull();
    expect(await screen.findByRole("switch", { name: "Mirror synchronization" })).toBeTruthy();
    expect(screen.getByText(en["mirrors.enablePlan"])).toBeTruthy();
  });

  it("refreshes evidence for the same Mirror after each accepted switch change", async () => {
    mirrorGrants.add("edit").add("show");
    const mirrorId = "mirror_1";
    const off = { ...orders.mirror, mirror_id: mirrorId };
    const on = { ...off, enabled: true, can_enable: false, can_disable: true };
    listMirrorTables.mockResolvedValue({ items: [{ ...table, mirror: off }] });
    const stoppedAt = "2026-01-01T00:00:00Z";
    const stop = { id: "stop-1", kind: "disable", state: "applied", control_revision: 2,
      mirror_id: mirrorId, observed_evidence_refs: ["source-stop"] };
    const stopped = {
      id: mirrorId, enabled: false, status: "disabled", published_generation_id: "g1", readiness: [],
      control: { control_revision: 2, applied_revision: 2, observed_at: stoppedAt,
        stop_ack: { operation_id: stop.id, source_operation_id: "source-stop", observed_at: stoppedAt } },
      operations: [stop],
    };
    const reopen = { id: "open-2", kind: "open", state: "pending", control_revision: 3, requested_at: stoppedAt };
    const reopened = { ...stopped, enabled: true, status: "waiting", control: { control_revision: 3 }, operations: [stop, reopen] };
    const stopping = { ...stopped, status: "disable_pending", control: { control_revision: 4 },
      operations: [stop, { ...stop, id: "stop-3", state: "pending", control_revision: 4 }] };
    const evidence = vi.fn().mockReturnValueOnce(stopped).mockReturnValueOnce(reopened).mockReturnValue(stopping);
    vi.stubGlobal("fetch", async (path: string, options: RequestInit) => {
      if (path === `/api/mirrors/${mirrorId}`) return Response.json({ mirror: evidence() });
      if (path === "/api/objects/obj_1/mirror" && options.method === "PUT") {
        return Response.json(JSON.parse(String(options.body)).enabled
          ? { mirror: on, operation_id: reopen.id } : { mirror: off, operation_id: "stop-3" });
      }
      throw new Error(`Unexpected request: ${path}`);
    });
    render(shell(createElement(MirrorTableDrawer, { objectId: orders.id })));
    const control = await openTableSetting();
    await screen.findByText(en["mirrors.event.stopConfirmed"], { exact: false });

    fireEvent.click(control);
    expect(await screen.findByText(en["mirrors.event.retained"])).toBeTruthy();
    fireEvent.click(control);
    fireEvent.click(await screen.findByRole("button", { name: "Confirm" }));
    expect(await screen.findByText(en["mirrors.event.disableRequested"])).toBeTruthy();
    expect(evidence).toHaveBeenCalledTimes(3);
  });

  it("withdraws the stale enable action and reports the problem when the server denies it", async () => {
    mirrorGrants.add("edit");
    getCatalogObject.mockResolvedValueOnce({ object: orders }).mockResolvedValue({
      object: { ...orders, mirror: null },
    });
    listMirrorTables.mockResolvedValueOnce({ items: [table] }).mockResolvedValue({ items: [] });
    const submit = stubMirrorPut(async () => new Response(
      JSON.stringify({ code: "AUTH_FORBIDDEN", detail: "Forbidden" }),
      { status: 403 },
    ));
    render(shell(createElement(CatalogObjectDetail, { objectId: orders.id })));

    fireEvent.click(await openTableSetting());
    expect(await screen.findByRole("alert")).toBeTruthy();
    expect(listMirrorTables).toHaveBeenCalledTimes(2);
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
    listMirrorTables.mockResolvedValueOnce({ items: [{ ...table, mirror: { enabled: true, can_enable: false, can_disable: true, mirror_id: null } }] });
    const control = await openTableSetting();
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

  it("lets a writer cancel or delete a mistakenly enrolled Mirror without reading management detail", async () => {
    mirrorGrants.add("edit");
    const token = "c".repeat(32);
    listMirrorTables.mockResolvedValueOnce({ items: [{ ...table, mirror: { ...orders.mirror, delete_token: token } }] })
      .mockResolvedValue({ items: [table] });
    const remove = vi.fn().mockResolvedValue(new Response(null, { status: 204 }));
    vi.stubGlobal("fetch", (path: string, options: RequestInit) => {
      if (path === `/api/objects/obj_1/mirror?delete_token=${token}` && options.method === "DELETE") return remove();
      throw new Error(`Unexpected request: ${path}`);
    });
    render(shell(createElement(MirrorTableDrawer, { objectId: orders.id })));
    await openTableSetting();
    const button = await screen.findByRole("button", { name: "Delete Mirror" });
    fireEvent.click(button);
    fireEvent.click(await screen.findByRole("button", { name: "Cancel" }));
    expect(remove).not.toHaveBeenCalled();
    fireEvent.click(button);
    const dialog = await screen.findByRole("dialog", { name: "Delete Mirror" });
    fireEvent.click(within(dialog).getByRole("button", { name: "Delete Mirror" }));
    await waitFor(() => expect(listMirrorTables).toHaveBeenCalledTimes(2));
    expect(remove).toHaveBeenCalledTimes(1);
    expect(screen.queryByRole("link", { name: "View mirror" })).toBeNull();
    await waitFor(() => expect(screen.queryByRole("button", { name: "Delete Mirror" })).toBeNull());
  });

  it("disables the setting while enable acceptance is pending", async () => {
    mirrorGrants.add("edit").add("show");
    getCatalogObject.mockResolvedValueOnce({ object: orders }).mockResolvedValue({
      object: { ...orders, mirror: { enabled: true, can_enable: false, can_disable: true, mirror_id: "mirror_1" } },
    });
    let finish!: (response: Response) => void;
    const submit = stubMirrorPut(() => new Promise<Response>((resolve) => { finish = resolve; }));
    render(shell(createElement(CatalogObjectDetail, { objectId: orders.id })));
    fireEvent.click(await openTableSetting());
    expect(screen.getByRole("switch", { name: "Mirror synchronization" }).hasAttribute("disabled")).toBe(true);
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
    fireEvent.click(await openTableSetting());
    view.rerender(shell(createElement(CatalogObjectDetail, { objectId: "other_object" })));
    expect(submit.mock.calls[0][0].signal?.aborted).toBe(true);
    await act(async () => finish(acceptedMirror()));
    expect(getCatalogObject).toHaveBeenCalledTimes(2);
    expect(openNotification).not.toHaveBeenCalled();
    expect(screen.queryByRole("link", { name: "View mirror" })).toBeNull();
  });

  it("returns a paged and filtered picker to the selected table and names its slot holder", async () => {
    mirrorGrants.add("show");
    window.history.replaceState(null, "", "/console/mirrors?mirrorTable=list&tableSource=source&tableQuery=sales%20order&tablePage=2");
    const candidate = { ...table, qualified_table: "public.sales orders", mirror: { ...orders.mirror, mirror_id: "m1" }, snapshot_holder: { mirror_id: "other", qualified_table: "public.shipment" } };
    listMirrorTables.mockResolvedValue({ items: [candidate], limit: 10, total: 11, offset: 10 });
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(new Response('{"items":[]}')));
    render(shell(createElement(MirrorTableDrawer)));

    const drawer = screen.getByRole("dialog");
    drawer.style.overflowY = "auto";
    drawer.scrollTop = 125;
    using visibleRows = vi.spyOn(HTMLButtonElement.prototype, "getClientRects")
      .mockReturnValue([new DOMRect(0, 0, 120, 24)] as unknown as DOMRectList);
    fireEvent.click(await screen.findByRole("button", { name: candidate.qualified_table }));
    expect(listMirrorTables.mock.calls[0][0]).toEqual({ source_id: "source", q: "sales order", limit: 10, offset: 10 });
    const holder = await screen.findByRole("link", { name: "public.shipment" });
    const origin = new URL(holder.getAttribute("href")!, window.location.href).searchParams.get("from");
    expect(origin).toBe(window.location.pathname + window.location.search);
    expect(origin).toContain("mirrorTable=obj_1");
    expect(origin).toContain("tablePage=2");
    drawer.scrollTop = 0;
    fireEvent.click(screen.getByRole("button", { name: "Back to tables" }));
    const row = await screen.findByRole("button", { name: candidate.qualified_table });
    await waitFor(() => expect(document.activeElement === row).toBe(true));
    expect(drawer.scrollTop).toBe(125);
    expect(listMirrorTables.mock.lastCall?.[0]).toMatchObject({ offset: 10, q: "sales order" });
  });

  it("restores the search draft when browser navigation interrupts a pending edit", async () => {
    window.history.replaceState(null, "", "/console/catalog?mirrorTable=list&tableQuery=public.old");
    listMirrorTables.mockResolvedValue({ items: [], limit: 10, total: 0, offset: 0 });
    const record = () => shell(createElement(MirrorTableDrawer));
    const view = render(record());
    const search = await screen.findByRole<HTMLInputElement>("textbox", { name: copy["mirrors.tableSearch"] });
    fireEvent.change(search, { target: { value: "outgoing" } });
    window.history.replaceState(null, "", "/console/catalog?mirrorTable=list&tableQuery=public.restored");
    view.rerender(record());
    expect(search.value).toBe("public.restored");
    await act(async () => { await new Promise(resolve => setTimeout(resolve, 350)); });
    expect(new URLSearchParams(window.location.search).get("tableQuery")).toBe("public.restored");
    expect(listMirrorTables.mock.lastCall?.[0].q).toBe("public.restored");
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

  it("renders the telemetry ribbon, source links, column coverage, and titleExtra status badges", async () => {
    getCatalogObject.mockResolvedValue({
      object: {
        id: "obj_1",
        source_id: "source",
        source: {
          id: "source",
          key: "demo",
          name: "Demo Postgres",
          engine: "postgresql",
        },
        schema_name: "public",
        name: "orders",
        object_type: "table",
        locator_key: "obj/postgresql/demo/public/table/orders",
        columns: [
          {
            id: "col_1",
            locator_key: "col/1",
            name: "id",
            data_type: "bigint",
            nullable: false,
            business_name: "Order ID",
            business_description: null,
            ordinal: 1,
            is_present: true,
          },
          {
            id: "col_2",
            locator_key: "col/2",
            name: "total",
            data_type: "numeric",
            nullable: true,
            business_name: null,
            business_description: null,
            ordinal: 2,
            is_present: true,
          },
        ],
        is_present: true,
        business_semantics_ready: false,
        estimated_rows: 1234,
        source_size_bytes: 1500000,
        open_questions: ["Verify currency unit"],
      },
    });
    render(shell(createElement(CatalogObjectDetail, { objectId: "obj_1" })));
    await screen.findByRole("heading", { name: "public.orders" });

    const header = document.querySelector("[data-page-header]")!;
    expect(header.textContent).toContain("Present");
    expect(header.textContent).toContain("Business semantics incomplete");

    const telemetry = screen.getByRole("region", {
      name: copy["catalog.detail.telemetryAria"],
    });
    expect(within(telemetry).getByText("obj/postgresql/demo/public/table/orders")).toBeTruthy();
    expect(within(telemetry).getByRole("button", { name: "Copy locator" })).toBeTruthy();

    const sourceLink = within(telemetry).getByRole("link", { name: "Demo Postgres" });
    expect(sourceLink.getAttribute("href")).toBe("/console/sources/source");

    const diffsLink = within(telemetry).getByRole("link", {
      name: copy["catalog.detail.structureDiffs"],
    });
    expect(diffsLink.getAttribute("href")).toBe("/console/sources/source?tab=diffs");

    expect(within(telemetry).getByText("1,234")).toBeTruthy();
    expect(within(telemetry).getByText("1.43 MB")).toBeTruthy();
    expect(within(telemetry).getByText("1 open questions")).toBeTruthy();

    const coverageBtn = within(telemetry).getByRole("button", {
      name: /1\/2 columns documented/,
    });
    fireEvent.click(coverageBtn);
    expect(screen.getByRole("tab", { selected: true }).textContent).toContain("Columns (2)");
    expect(screen.getByRole("tablist").style.flexWrap).toBe("nowrap");
    expect(
      screen.queryByRole("region", { name: copy["catalog.detail.telemetryAria"] }),
    ).toBeNull();
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
