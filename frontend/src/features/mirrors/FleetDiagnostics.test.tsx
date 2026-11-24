/** @vitest-environment jsdom */
import { createElement, forwardRef, type ComponentProps, type ReactNode } from "react";
import { MantineProvider } from "@mantine/core";
import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeAll, beforeEach, expect, it, vi } from "vitest";
import en from "@/locales/en-US/common.json";
import { getFleetOverview, getSourceDiagnostics, listFleetRuntimes, listFleetSources } from "./api";
import { diagnosticFixture } from "./diagnostics.testFixtures";
import { FleetDiagnosticExplorer } from "./FleetDiagnostics";
import { createFleetFixture } from "./fleet.testFixtures";
import { SourceDiagnostics } from "./SourceDiagnostics";

const navigation = vi.hoisted(() => ({ search: new URLSearchParams() }));
vi.mock("next/navigation", () => ({ useSearchParams: () => navigation.search }));
vi.mock("@refinedev/core", () => ({ useTranslate: () => (key: string, params: Record<string, unknown> = {}) => {
  let text = (en as Record<string, string>)[key] ?? key;
  for (const [name, value] of Object.entries(params)) text = text.replaceAll(`{{${name}}}`, String(value));
  return text;
} }));
vi.mock("@/components/navigation/useConsoleNavigation", () => ({
  useConsoleLocation: () => ({ search: new URLSearchParams(window.location.search), href: window.location.pathname + window.location.search }),
  useConsoleNavigation: () => ({ push: vi.fn(), replace: vi.fn() }),
}));
vi.mock("@/components/navigation/ConsoleLink", () => ({ ConsoleLink: forwardRef<HTMLAnchorElement, ComponentProps<"a">>((props, ref) => createElement("a", { ...props, ref })) }));
vi.mock("@/components/layout/PageChrome", () => ({ PageChrome: () => null }));
vi.mock("@/components/feedback/presentProblemNotification", () => ({ presentProblemNotification: vi.fn() }));
vi.mock("./api", () => ({ getFleetOverview: vi.fn(), getSourceDiagnostics: vi.fn(), listFleetRuntimes: vi.fn(), listFleetSources: vi.fn() }));

beforeAll(() => {
  window.matchMedia = vi.fn().mockImplementation(query => ({ matches: false, media: query, addEventListener: vi.fn(), removeEventListener: vi.fn(), addListener: vi.fn(), removeListener: vi.fn() }));
  global.ResizeObserver = class { observe() {} unobserve() {} disconnect() {} };
});
beforeEach(() => {
  vi.clearAllMocks();
  address("");
  const fixture = createFleetFixture(40);
  vi.mocked(listFleetSources).mockImplementation(async query => fixture.sourcePage(query));
  vi.mocked(listFleetRuntimes).mockImplementation(async query => fixture.runtimePage(query));
  vi.mocked(getFleetOverview).mockResolvedValue(fixture.overview());
  vi.mocked(getSourceDiagnostics).mockResolvedValue(diagnosticFixture());
});
afterEach(() => { cleanup(); vi.restoreAllMocks(); });
const wrap = ({ children }: { children: ReactNode }) => <MantineProvider>{children}</MantineProvider>;
function address(query: string) {
  navigation.search = new URLSearchParams(query);
  window.history.replaceState(null, "", `/console/mirrors/diagnostics${query ? `?${query}` : ""}`);
}

it("lets a reader type a Source name with spaces and publishes it without a history entry", async () => {
  const push = vi.spyOn(window.history, "pushState");
  render(<FleetDiagnosticExplorer data={createFleetFixture(40).overview()} scope={{}} origin="/console/mirrors/diagnostics" />, { wrapper: wrap });
  const input = screen.getByRole("textbox", { name: "Source name or ID" });
  fireEvent.change(input, { target: { value: "Sales " } });
  expect((input as HTMLInputElement).value).toBe("Sales ");
  fireEvent.change(input, { target: { value: "Sales warehouse" } });
  fireEvent.keyDown(input, { key: "Enter" });
  await waitFor(() => expect(vi.mocked(listFleetSources).mock.calls.at(-1)?.[0].q).toBe("Sales warehouse"));
  expect(new URLSearchParams(window.location.search).get("q")).toBe("Sales warehouse");
  expect(push).not.toHaveBeenCalled();
});

it("refreshes finder rows with fleet observations and marks retained rows stale on failure", async () => {
  const fixture = createFleetFixture(4);
  vi.mocked(listFleetSources).mockImplementation(async query => fixture.sourcePage(query));
  vi.mocked(listFleetRuntimes).mockImplementation(async query => fixture.runtimePage(query));
  const data = fixture.overview();
  const { rerender } = render(<FleetDiagnosticExplorer data={data} scope={{}} origin="/console/mirrors/diagnostics" />, { wrapper: wrap });
  await screen.findByRole("link", { name: "PostgreSQL 0002" });
  const before = vi.mocked(listFleetSources).mock.calls.length;
  vi.mocked(listFleetSources).mockRejectedValueOnce(new Error("offline"));
  rerender(<FleetDiagnosticExplorer data={{ ...data, observed_at: "2026-11-24T12:00:02Z" }} scope={{}} origin="/console/mirrors/diagnostics" />);
  await waitFor(() => expect(vi.mocked(listFleetSources).mock.calls.length).toBeGreaterThan(before));
  await waitFor(() => expect(screen.getByRole("status").textContent).toContain("stale"));
  const row = screen.getByRole("link", { name: "PostgreSQL 0002" }).closest("tr")!;
  expect(within(row).getByText("Stale")).toBeTruthy();
  vi.mocked(listFleetSources).mockRejectedValueOnce(new Error("offline"));
  const input = screen.getByRole("textbox", { name: "Source name or ID" });
  fireEvent.change(input, { target: { value: "another" } });
  fireEvent.keyDown(input, { key: "Enter" });
  await waitFor(() => expect(screen.queryByRole("link", { name: "PostgreSQL 0002" })).toBeNull());
});

it("restores a runtime results page from the URL when the scope changes", async () => {
  const data = createFleetFixture(40).overview();
  address("runtime_id=capture-01&runtime_results_page=3");
  const { rerender } = render(<FleetDiagnosticExplorer data={data} scope={{ runtime_id: "capture-01" }} origin={window.location.pathname + window.location.search} />, { wrapper: wrap });
  await waitFor(() => expect(vi.mocked(listFleetRuntimes).mock.calls.at(-1)?.[0].offset).toBe(24));
  address("runtime_results_page=2");
  rerender(<FleetDiagnosticExplorer data={data} scope={{}} origin={window.location.pathname + window.location.search} />);
  await waitFor(() => expect(vi.mocked(listFleetRuntimes).mock.calls.at(-1)?.[0].offset).toBe(12));
  expect(new URLSearchParams(window.location.search).get("runtime_results_page")).toBe("2");
});

it("applies Source precedence to both Diagnostics reads", async () => {
  address("source_id=source-0002&runtime_id=another-runtime");
  render(<SourceDiagnostics />, { wrapper: wrap });
  await waitFor(() => expect(getSourceDiagnostics).toHaveBeenCalled());
  const query = vi.mocked(getSourceDiagnostics).mock.calls[0][0];
  expect(query.get("source_id")).toBe("source-0002");
  expect(query.has("runtime_id")).toBe(false);
  expect(vi.mocked(getFleetOverview).mock.calls[0][0]).toEqual({ source_id: "source-0002" });
});
