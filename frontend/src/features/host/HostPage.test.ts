/** @vitest-environment jsdom */

import { MantineProvider } from "@mantine/core";
import { act, cleanup, fireEvent, render, screen, within } from "@testing-library/react";
import { createElement, type ReactNode } from "react";
import { afterEach, beforeEach, expect, it, vi } from "vitest";

import { HostPage } from "./HostPage";
import type { HostRead, HostSpan } from "./types";
import en from "@/locales/en-US/common.json";
import zh from "@/locales/zh-CN/common.json";

const fetchMock = vi.hoisted(() => vi.fn());
vi.mock("@refinedev/core", () => ({
  matchResourceFromRoute: () => ({ found: false }),
  useTranslate: () => (key: string, params?: Record<string, unknown>) => {
    let text = (en as Record<string, string>)[key] ?? key;
    for (const [name, value] of Object.entries(params ?? {})) text = text.replace(`{{${name}}}`, String(value));
    return text;
  },
  useGetLocale: () => () => "en-US",
  useCan: () => ({ data: { can: true } }),
  usePermissions: () => ({ data: ["host:read"] }),
  useBreadcrumb: () => ({ breadcrumbs: [] }),
}));
vi.mock("@/providers/time-zones", () => ({ useTimeZones: () => ({ items: [] }) }));
vi.mock("@/providers/session-store", () => ({
  useSessionStore: (select: (state: unknown) => unknown) => select({ user: { locale: "en-US", display_timezone: "America/New_York" } }),
}));
vi.mock("@/features/branding/BrandingProvider", () => ({ useBranding: () => ({ brandName: "Refraq" }) }));
vi.mock("next/navigation", () => ({
  usePathname: () => "/console/host",
  useRouter: () => ({ push: vi.fn(), replace: vi.fn(), refresh: vi.fn() }),
  useSearchParams: () => new URLSearchParams(window.location.search),
}));
vi.mock("next/link", () => ({
  default: ({ href, children }: { href: string; children?: ReactNode }) => createElement("a", { href }, children),
  useLinkStatus: () => ({ pending: false }),
}));
const notify = vi.hoisted(() => vi.fn());
vi.mock("@/components/feedback/presentProblemNotification", () => ({ presentProblemNotification: notify }));

const end = "2026-11-12T00:00:00Z";
const names = ["postgres", "redis", "api", "worker", "beat", "mcp", "entity-mcp", "web"];
const samples = [{ t: "2026-11-11T23:58:00Z", v: 1 }, { t: "2026-11-11T23:59:00Z", v: null }, { t: end, v: 2 }];
function body(span: HostSpan = "day"): HostRead {
  return {
    span, start: "2026-11-11T00:00:00Z", end, step_seconds: 121,
    tiles: { cpu: { online_count: 4, busy_share: 0.25 }, memory: { used_bytes: 6100, total_bytes: 8192 }, swap: { used_bytes: 0, total_bytes: 0 }, postgres: { backends: 17, max_connections: 100 }, filesystems: [{ mount: "/data", type: "xfs", used_bytes: 750, total_bytes: 4000, used_share: 0.75, free_inodes: null }] },
    charts: {
      cpu_modes: [{ mode: "guest_nice", samples }], run_queue: samples,
      pressure: { cpu: { waiting: samples, stalled: [] }, memory: { waiting: [], stalled: [] }, io: { waiting: [], stalled: [] } },
      filesystems: [{ mount: "/data", type: "xfs", available: samples, delta: [{ t: end, v: -17 }] }, { mount: "/archive", type: "zfs", available: [], delta: [] }],
      disks: [{ device: "nvme1n1", busy_share: samples, queue_length: samples }],
      postgres: { backends: samples, idle_in_transaction: samples, idle_in_transaction_aborted: samples, checkpoint_timed: samples, checkpoint_requested: samples, checkpoint_write_time: samples, checkpoint_sync_time: samples, checkpoint_buffers_written: samples, temp_files: samples, temp_bytes: samples },
      services: names.map((service) => ({ service, cpu_seconds: service === "redis" ? [] : samples, memory_bytes: service === "redis" ? [] : samples })),
    },
  };
}
function response(value: unknown, status = 200) {
  return new Response(JSON.stringify(value), { status, headers: { "content-type": status === 200 ? "application/json" : "application/problem+json" } });
}
function pending() {
  let resolve!: (value: Response) => void;
  const promise = new Promise<Response>((done) => { resolve = done; });
  return { promise, resolve: (value: unknown, status = 200) => resolve(response(value, status)) };
}
function page() { return render(createElement(MantineProvider, { env: "test" }, createElement(HostPage))); }
function tab(name: string) { fireEvent.click(screen.getByRole("tab", { name, exact: true })); }
function span(value: HostSpan) { fireEvent.change(screen.getByRole("combobox", { name: "History period" }), { target: { value } }); }
async function ready() { await screen.findByText("25%"); }
function requests() { return fetchMock.mock.calls.map((call) => new URL(String(call[0]), "http://test").searchParams.get("span")); }

beforeEach(() => {
  window.history.replaceState(null, "", "/console/host");
  fetchMock.mockReset(); notify.mockReset();
  vi.stubGlobal("fetch", fetchMock);
  vi.stubGlobal("ResizeObserver", class { observe() {} disconnect() {} });
  Object.defineProperty(window, "matchMedia", { writable: true, value: () => ({ matches: false, addEventListener() {}, removeEventListener() {} }) });
});
afterEach(() => { cleanup(); vi.unstubAllGlobals(); });

it("opens compact Overview and lazily discloses CPU diagnostics without another read", async () => {
  fetchMock.mockResolvedValue(response(body())); page(); await ready();
  expect(screen.getByRole("tab", { name: "Overview" }).getAttribute("aria-selected")).toBe("true");
  expect(screen.getAllByRole("heading", { level: 1 })).toHaveLength(1);
  expect(screen.queryByRole("img", { name: "CPU modes (CPU-s/s)" })).toBeNull();
  fireEvent.click(screen.getByText("Advanced CPU modes", { selector: "summary" }));
  expect(screen.getByText("guest_nice")).toBeTruthy();
  expect(screen.getByText("No swap configured")).toBeTruthy();
  expect(screen.getAllByText("0 B")).toHaveLength(2);
  expect(screen.getByText(/Query snapshot time:/).textContent).toContain("7:00:00 PM");
  expect(fetchMock).toHaveBeenCalledTimes(1);
});

it("selects independent filesystem and disk histories while keeping identities discoverable", async () => {
  fetchMock.mockResolvedValue(response(body())); page(); await ready(); tab("Storage");
  expect(window.location.search).toContain("tab=storage");
  const select = screen.getByRole("combobox", { name: "Inspect resource history" });
  expect(within(select).getByRole("option", { name: "/archive (zfs)" })).toBeTruthy();
  expect(screen.getAllByRole("img")).toHaveLength(2);
  expect(screen.getAllByText(/Free inodes: —/)).toHaveLength(2);
  const delta = screen.getByRole("img", { name: "/data (xfs) · Space change per sample" });
  expect(delta.querySelectorAll("circle[data-series]")).toHaveLength(1);
  fireEvent.change(select, { target: { value: JSON.stringify(["disk", "nvme1n1"]) } });
  expect(screen.getByRole("img", { name: "nvme1n1 · Queue length" })).toBeTruthy();
  expect(screen.queryByRole("img", { name: /Available/ })).toBeNull();
  expect(fetchMock).toHaveBeenCalledTimes(1);
});

it("prioritizes connection and idle states and discloses cumulative counter diagnostics", async () => {
  fetchMock.mockResolvedValue(response(body())); page(); await ready(); tab("PostgreSQL");
  expect(screen.getAllByRole("img")).toHaveLength(3);
  expect(screen.getByRole("img", { name: "Idle in transaction (aborted)" })).toBeTruthy();
  fireEvent.click(screen.getByText("Checkpoint counters", { selector: "summary" }));
  expect(screen.getByRole("img", { name: "Checkpoint write time counter (unit unknown)" })).toBeTruthy();
  fireEvent.click(screen.getByText("Temporary-file counters", { selector: "summary" }));
  expect(screen.getByRole("img", { name: "Temporary file bytes" })).toBeTruthy();
  expect(screen.getAllByRole("img")).toHaveLength(10);
});

it("compares selected services in two shared charts and preserves gaps, zeros and absent identities", async () => {
  fetchMock.mockResolvedValue(response(body())); page(); await ready(); tab("Services");
  for (const name of names) expect(screen.getByRole("checkbox", { name, exact: true })).toBeTruthy();
  const inventory = screen.getByRole("checkbox", { name: "api", exact: true }).closest('[data-service]')!;
  expect(within(inventory as HTMLElement).getByText("2 CPU-s/step")).toBeTruthy();
  expect(within(inventory as HTMLElement).getAllByRole("time")[0]?.textContent).toContain("7:00:00 PM");
  expect(screen.getAllByRole("img")).toHaveLength(2);
  const cpu = screen.getByRole("img", { name: "Estimated CPU time per step (CPU-s/step)" });
  expect(cpu.querySelectorAll('circle[data-series="api"]')).toHaveLength(2);
  expect(cpu.querySelectorAll('polyline[data-series="api"]')).toHaveLength(0);
  fireEvent.click(screen.getByRole("checkbox", { name: "redis", exact: true }));
  expect(cpu.querySelectorAll('[data-series="redis"]')).toHaveLength(0);
  for (const name of ["api", "worker", "redis"]) fireEvent.click(screen.getByRole("checkbox", { name, exact: true }));
  expect(screen.queryByRole("img")).toBeNull();
  expect(screen.getByText("Select a service to inspect its CPU and memory history.")).toBeTruthy();
});

it("uses compact section empty states instead of empty plots and retains all eight services", async () => {
  const empty = body();
  empty.charts.run_queue = []; empty.charts.cpu_modes = [];
  empty.charts.pressure.cpu.waiting = []; empty.charts.filesystems = []; empty.tiles.filesystems = []; empty.charts.disks = [];
  for (const key of Object.keys(empty.charts.postgres) as (keyof HostRead["charts"]["postgres"])[]) empty.charts.postgres[key] = [];
  empty.charts.services = names.map((service) => ({ service, cpu_seconds: [], memory_bytes: [] }));
  fetchMock.mockResolvedValue(response(empty)); page(); await ready();
  expect(screen.queryByRole("img")).toBeNull();
  tab("Storage"); expect(screen.getByText(en["host.empty.storage"])).toBeTruthy();
  tab("PostgreSQL"); expect(screen.getByText(en["host.empty.postgres"])).toBeTruthy();
  tab("Services"); expect(screen.getAllByRole("checkbox")).toHaveLength(8);
  expect(screen.queryByRole("img")).toBeNull();
});

it("restores URL span/panel and falls back from invalid URL values", async () => {
  window.history.replaceState(null, "", "/console/host?span=hour&tab=services");
  fetchMock.mockResolvedValue(response(body("hour"))); page();
  await screen.findByRole("checkbox", { name: "api", exact: true });
  expect(requests()).toEqual(["hour"]);
  cleanup(); window.history.replaceState(null, "", "/console/host?span=bad&tab=bad");
  fetchMock.mockResolvedValue(response(body())); page(); await ready();
  expect(screen.getByRole("tab", { name: "Overview" }).getAttribute("aria-selected")).toBe("true");
  expect(requests()).toEqual(["hour", "day"]);
});

it("deduplicates refresh, retains successful snapshots on failure and retries selected history with trigger focus", async () => {
  const replacement = pending();
  fetchMock.mockResolvedValueOnce(response(body())).mockReturnValueOnce(replacement.promise).mockResolvedValueOnce(response({ ...body("hour"), end: "2026-11-12T00:01:00Z" }));
  page(); await ready();
  span("hour");
  const refresh = screen.getByRole("button", { name: "Refresh" }); refresh.focus(); fireEvent.click(refresh); fireEvent.click(refresh);
  expect(requests()).toEqual(["day", "hour"]);
  expect(screen.getByText("Displayed history: Last 24 hours")).toBeTruthy();
  await act(async () => replacement.resolve({ code: "HOST_SERIES_UNAVAILABLE", status: 503 }, 503));
  expect(screen.getByText("Previous snapshot retained")).toBeTruthy();
  expect(screen.getByText(/Query snapshot time:/).querySelector("time")?.getAttribute("datetime")).toBe(end);
  fireEvent.click(refresh);
  await screen.findByText("Displayed history: Last hour");
  expect(requests()).toEqual(["day", "hour", "hour"]);
  expect(document.activeElement).toBe(refresh);
  expect(notify).toHaveBeenCalledTimes(1);
});

it.each([200, 503])("ignores obsolete success/failure across spans and newer same-span refresh (%s)", async (status) => {
  const old = pending(); const newest = pending();
  fetchMock.mockReturnValueOnce(old.promise).mockResolvedValueOnce(response(body("hour"))).mockResolvedValueOnce(response(body("retained"))).mockResolvedValueOnce(response(body("hour"))).mockReturnValueOnce(newest.promise);
  page(); span("hour"); await ready(); span("retained"); await screen.findByText("Displayed history: Samples still in the store"); span("hour"); await screen.findByText("Displayed history: Last hour");
  fireEvent.click(screen.getByRole("button", { name: "Refresh" }));
  await act(async () => old.resolve(status === 200 ? body() : { code: "HOST_SERIES_UNAVAILABLE", status }, status));
  expect(screen.getByRole("status").textContent).toBe("Loading: Last hour");
  await act(async () => newest.resolve({ ...body("hour"), end: "2026-11-12T00:03:00Z" }));
  expect(screen.getByText(/Query snapshot time:/).querySelector("time")?.getAttribute("datetime")).toBe("2026-11-12T00:03:00Z");
  expect(notify).not.toHaveBeenCalled();
});

it("retries an initial outage without invented zeros and ignores responses after unmount", async () => {
  fetchMock.mockResolvedValueOnce(response({ code: "HOST_SERIES_UNAVAILABLE", status: 503 }, 503)).mockResolvedValueOnce(response(body()));
  page(); fireEvent.click(await screen.findByRole("button", { name: en["status.unloaded"] })); await ready();
  expect(requests()).toEqual(["day", "day"]);
  cleanup(); const late = pending(); fetchMock.mockReturnValueOnce(late.promise); page(); cleanup();
  await act(async () => late.resolve({ code: "HOST_SERIES_UNAVAILABLE", status: 503 }, 503));
  expect(notify).toHaveBeenCalledTimes(1);
});

it("marks URL-driven range reads busy, retains facts and rejects obsolete URL responses", async () => {
  const obsolete = pending(); const newest = pending();
  fetchMock.mockResolvedValueOnce(response(body())).mockReturnValueOnce(obsolete.promise).mockReturnValueOnce(newest.promise);
  const view = page(); await ready();
  const navigate = (value: HostSpan) => {
    window.history.replaceState(null, "", `/console/host?span=${value}&tab=services`);
    view.rerender(createElement(MantineProvider, { env: "test" }, createElement(HostPage)));
  };
  navigate("hour");
  expect(requests()).toEqual(["day", "hour"]);
  expect(screen.getByRole("status").textContent).toBe("Loading: Last hour");
  expect(screen.getByRole("button", { name: "Refresh" }).getAttribute("aria-busy")).toBe("true");
  expect(screen.getByText("Displayed history: Last 24 hours")).toBeTruthy();
  navigate("retained");
  await act(async () => obsolete.resolve(body("hour")));
  expect(screen.getByRole("status").textContent).toBe("Loading: Samples still in the store");
  await act(async () => newest.resolve(body("retained")));
  expect(screen.getByRole("status").textContent).toBe("Loaded: Samples still in the store");
  expect(requests()).toEqual(["day", "hour", "retained"]);
});

it.each([200, 503])("ignores an obsolete request for the same span during a newer refresh (%s)", async (status) => {
  const oldHour = pending(); const newest = pending();
  fetchMock.mockResolvedValueOnce(response(body())).mockReturnValueOnce(oldHour.promise).mockResolvedValueOnce(response(body("retained"))).mockResolvedValueOnce(response(body("hour"))).mockReturnValueOnce(newest.promise);
  page(); await ready(); span("hour"); span("retained");
  await screen.findByText("Displayed history: Samples still in the store");
  span("hour"); await screen.findByText("Displayed history: Last hour");
  fireEvent.click(screen.getByRole("button", { name: "Refresh" }));
  await act(async () => oldHour.resolve(status === 200 ? body("hour") : { code: "HOST_SERIES_UNAVAILABLE", status }, status));
  expect(screen.getByRole("status").textContent).toBe("Loading: Last hour");
  expect(notify).not.toHaveBeenCalled();
  await act(async () => newest.resolve({ ...body("hour"), end: "2026-11-12T00:04:00Z" }));
  expect(screen.getByText(/Query snapshot time:/).querySelector("time")?.getAttribute("datetime")).toBe("2026-11-12T00:04:00Z");
});

it("retains hidden panel selections and joins filesystem histories by mount and type", async () => {
  const reading = body();
  reading.charts.filesystems.push({ mount: "/data", type: "ext4", available: [{ t: end, v: 4096 }], delta: [] });
  reading.charts.services[2]!.cpu_seconds = [{ t: end, v: 0 }];
  fetchMock.mockResolvedValue(response(reading)); page(); await ready(); tab("Storage");
  fireEvent.change(screen.getByRole("combobox", { name: "Inspect resource history" }), { target: { value: JSON.stringify(["mount", "/data", "ext4"]) } });
  expect(screen.getByRole("img", { name: "/data (ext4) · Available" })).toBeTruthy();
  expect(screen.getAllByText("4 KiB").length).toBeGreaterThan(0);
  tab("Services");
  const inventory = screen.getByRole("checkbox", { name: "api", exact: true }).closest('[data-service]')!;
  expect(within(inventory as HTMLElement).getByText("0 CPU-s/step")).toBeTruthy();
  fireEvent.click(screen.getByRole("checkbox", { name: "worker", exact: true }));
  tab("Storage");
  expect((screen.getByRole("combobox", { name: "Inspect resource history" }) as HTMLSelectElement).value).toBe(JSON.stringify(["mount", "/data", "ext4"]));
  expect(screen.queryByRole("checkbox")).toBeNull();
  tab("Services");
  expect((screen.getByRole("checkbox", { name: "worker", exact: true }) as HTMLInputElement).checked).toBe(false);
  expect(screen.queryByRole("combobox", { name: "Inspect resource history" })).toBeNull();
  expect(fetchMock).toHaveBeenCalledTimes(1);
});

it("maps each PostgreSQL diagnostic to its own response field", async () => {
  const reading = body();
  const fields = Object.keys(reading.charts.postgres) as (keyof HostRead["charts"]["postgres"])[];
  fields.forEach((field, index) => { reading.charts.postgres[field] = [{ t: end, v: index + 10 }]; });
  fetchMock.mockResolvedValue(response(reading)); page(); await ready(); tab("PostgreSQL");
  fireEvent.click(screen.getByText("Checkpoint counters", { selector: "summary" }));
  fireEvent.click(screen.getByText("Temporary-file counters", { selector: "summary" }));
  const titles = ["Connections", "Idle in transaction", "Idle in transaction (aborted)", "Checkpoints timed", "Checkpoints requested", "Checkpoint write time counter (unit unknown)", "Checkpoint sync time counter (unit unknown)", "Checkpoint buffers written", "Temporary files", "Temporary file bytes"];
  titles.forEach((title, index) => {
    const chart = screen.getByRole("img", { name: title, exact: true }).closest(".mantine-Stack-root")!;
    expect(within(chart as HTMLElement).getByText(`${index + 10}${index === 9 ? " B" : ""}`, { selector: "span" })).toBeTruthy();
  });
});

it("localizes malformed snapshot time without losing resource facts", async () => {
  fetchMock.mockResolvedValue(response({ ...body(), end: "malformed" })); page(); await ready();
  expect(screen.getByText(/Query snapshot time:/).textContent).toContain(en["problems.API_CONTRACT_INVALID"]);
  expect(screen.getByText("5.96 KiB")).toBeTruthy();
});

it("contains matching localized Host keys and preserves unit caveats", () => {
  expect(Object.keys(en).filter((key) => key.startsWith("host.")).sort()).toEqual(Object.keys(zh).filter((key) => key.startsWith("host.")).sort());
  expect(en["host.service.cpu"]).toContain("CPU-s/step");
  expect(en["host.postgres.counterHelp"]).toContain("cumulative counters, not rates");
});
