/** @vitest-environment jsdom */
import { createElement, forwardRef, type ComponentProps, type ReactNode } from "react";
import { MantineProvider, Table } from "@mantine/core";
import { cleanup, fireEvent, render, screen, within } from "@testing-library/react";
import { afterEach, beforeAll, expect, it, vi } from "vitest";
import en from "@/locales/en-US/common.json";
import { FleetOverviewContent } from "./FleetOverview";
import { FleetThroughputChart, throughputRuns } from "./FleetThroughputChart";
import { InventoryRow } from "./MirrorInventory";
import { createFleetFixture } from "./fleet.testFixtures";
import { OperationsNavigation, operationsHref, operationsScope } from "./OperationsNavigation";
import { decimalBytes } from "./fleetFormat";

const location = vi.hoisted(() => ({ pathname: "/console/mirrors", search: "" }));
vi.mock("@refinedev/core", () => ({ useTranslate: () => (key: string, params: Record<string, unknown> = {}) => {
  let text = (en as Record<string, string>)[key] ?? key;
  for (const [name, value] of Object.entries(params)) text = text.replaceAll(`{{${name}}}`, String(value));
  return text;
}, useCan: () => ({ data: { can: true } }) }));
vi.mock("@/components/navigation/useConsoleNavigation", () => ({
  useConsoleLocation: () => ({ pathname: location.pathname, search: new URLSearchParams(location.search), href: location.pathname + (location.search ? `?${location.search}` : "") }),
  useConsoleNavigation: () => ({ push: vi.fn(), replace: vi.fn() }),
}));
vi.mock("@/components/navigation/ConsoleLink", () => ({ ConsoleLink: forwardRef<HTMLAnchorElement, ComponentProps<"a">>((props, ref) => createElement("a", { ...props, ref })) }));
vi.mock("@/components/layout/PageChrome", () => ({ PageChrome: () => null }));

beforeAll(() => {
  window.matchMedia = vi.fn().mockImplementation(query => ({ matches: false, media: query, addEventListener: vi.fn(), removeEventListener: vi.fn(), addListener: vi.fn(), removeListener: vi.fn() }));
  global.ResizeObserver = class { observe() {} unobserve() {} disconnect() {} };
});
afterEach(() => { cleanup(); location.pathname = "/console/mirrors"; location.search = ""; });
const wrap = ({ children }: { children: ReactNode }) => <MantineProvider>{children}</MantineProvider>;

it("reconciles 1,024-Source attention totals with all pages and preserves Source scope in drill-downs", () => {
  const fixture = createFleetFixture();
  const data = fixture.overview();
  const inventory = fixture.inventory({ grouped_state: "attention", limit: 12, offset: 12 });
  expect(data.source_count).toBe(1024);
  expect(data.attention_count).toBe(inventory.total);
  expect(inventory.items).toHaveLength(12);
  render(<FleetOverviewContent data={data} scope={{ runtime_id: "capture-01" }} origin="/console/mirrors" rank="size" onRankChange={vi.fn()} />, { wrapper: wrap });
  const totals = screen.getByRole("region", { name: "Fleet totals" });
  expect(within(totals).getByRole("link", { name: String(data.attention_count) }).getAttribute("href"))
    .toBe("/console/mirrors/inventory?grouped_state=attention&runtime_id=capture-01");
  expect(screen.getByRole("link", { name: "Failed 94" }).getAttribute("href"))
    .toBe("/console/mirrors/diagnostics?health=failed&runtime_id=capture-01");
  expect(screen.getByText(/Showing 8 of 1024 Sources/)).toBeTruthy();
});

it("counts retained stopped copies as published and exposes attention reasons beside publication", () => {
  const fixture = createFleetFixture();
  const retained = fixture.mirrors.find(row => row.grouped_state === "stopped" && row.published_generation_id)!;
  expect(fixture.overview().published_count).toBe(fixture.mirrors.filter(row => row.published_generation_id).length);
  render(<Table><Table.Tbody><InventoryRow mirror={{ ...retained, grouped_state: "attention", attention_cause: "continuity" }} attention origin="/console/mirrors/inventory?page=3" /></Table.Tbody></Table>, { wrapper: wrap });
  const row = screen.getByRole("row");
  expect(within(row).getByText("Log continuity")).toBeTruthy();
  expect(within(row).getByText("Published copy")).toBeTruthy();
  expect(within(row).getByText("Retained after stop")).toBeTruthy();
  expect(within(row).getByRole("link").getAttribute("href")).toContain("from=%2Fconsole%2Fmirrors%2Finventory%3Fpage%3D3");
  expect(within(row).queryByText(retained.estimated_rows!.toLocaleString())).toBeNull();
});

it("leaves measurement gaps, distinguishes zero and inspects both series with the keyboard in UTC", () => {
  const data = createFleetFixture(1).throughput();
  const change = vi.fn();
  render(<FleetThroughputChart data={data} hours="6" onHoursChange={change} />, { wrapper: wrap });
  expect(throughputRuns(data.points, "received")).toHaveLength(2);
  const slider = screen.getByRole("slider");
  fireEvent.keyDown(slider, { key: "Home" });
  expect(slider.getAttribute("aria-valuetext")).toContain("2026-11-24 06:15:00 UTC; CDC received:");
  fireEvent.change(slider, { target: { value: "6" } });
  expect(slider.getAttribute("aria-valuetext")).toContain("CDC received: Unavailable");
  expect(slider.getAttribute("aria-valuetext")).not.toContain("Mirror committed: Unavailable");
  fireEvent.change(slider, { target: { value: "13" } });
  expect(slider.getAttribute("aria-valuetext")).toContain("CDC received: 0 MB/s; Mirror committed: 0 MB/s");
  fireEvent.click(screen.getByRole("radio", { name: "24h" }));
  expect(change).toHaveBeenCalledWith("24");
});

it("keeps scope across the operations views and limits chart and Inventory query tokens to their views", () => {
  location.search = "source_id=source-0010&hours=24&rank=attention&grouped_state=attention";
  render(<OperationsNavigation view="overview" scope={{ source_id: "source-0010" }} />, { wrapper: wrap });
  const navigation = screen.getByRole("navigation", { name: "Operations views" });
  expect(within(navigation).getByRole("link", { name: "Overview" }).getAttribute("href")).toBe("/console/mirrors?hours=24&rank=attention&source_id=source-0010");
  expect(within(navigation).getByRole("link", { name: "Inventory" }).getAttribute("href")).toBe("/console/mirrors/inventory?grouped_state=attention&source_id=source-0010");
  expect(within(navigation).getByRole("link", { name: "Diagnostics" }).getAttribute("href")).toBe("/console/mirrors/diagnostics?source_id=source-0010");
  expect(within(navigation).getByRole("link", { name: "Deploy and connect" }).getAttribute("href")).toBe("/console/mirrors/setup?source_id=source-0010");
  expect(operationsScope(new URLSearchParams("source_id=s&runtime_id=r"))).toEqual({ source_id: "s" });
  expect(operationsHref("overview", { runtime_id: "capture/a" })).toBe("/console/mirrors?runtime_id=capture%2Fa");
  expect(decimalBytes(1_000_000)).toBe("1 MB");
});
