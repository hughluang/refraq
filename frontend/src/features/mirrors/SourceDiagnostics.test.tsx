/** @vitest-environment jsdom */
import { createElement, forwardRef, type ComponentProps, type ReactNode } from "react";
import { MantineProvider } from "@mantine/core";
import { cleanup, fireEvent, render, screen, within, waitFor, renderHook, act } from "@testing-library/react";
import { afterEach, beforeAll, expect, it, vi } from "vitest";
import en from "@/locales/en-US/common.json";
import { DiagnosticContent } from "./SourceDiagnostics";
import { MeasurementContent } from "./MirrorMeasurements";
import { diagnosticFixture, measurementsFixture, observed } from "./diagnostics.testFixtures";
import { useDiagnosticRead } from "./useDiagnosticRead";
import { ApiError } from "@/lib/api";
import { AggregateTopology } from "./FleetDiagnostics";
import { createFleetFixture } from "./fleet.testFixtures";

vi.mock("@refinedev/core", () => ({ useTranslate: () => (key: string, params: Record<string, unknown> = {}) => {
  let text = (en as Record<string, string>)[key] ?? key;
  for (const [name, value] of Object.entries(params)) text = text.replaceAll(`{{${name}}}`, String(value));
  return text;
} }));
vi.mock("@/hooks/useFormatInstant", () => ({ useFormatInstant: () => (value: string | null) => value ?? "—" }));
vi.mock("@/components/layout/PageChrome", () => ({ PageChrome: () => null }));
vi.mock("@/components/feedback/presentProblemNotification", () => ({ presentProblemNotification: vi.fn() }));
vi.mock("@/components/navigation/ConsoleLink", () => ({ ConsoleLink: forwardRef<HTMLAnchorElement, ComponentProps<"a">>((props, ref) => createElement("a", { ...props, ref })) }));

beforeAll(() => {
  window.matchMedia = vi.fn().mockImplementation(query => ({ matches: false, media: query, addEventListener: vi.fn(), removeEventListener: vi.fn(), addListener: vi.fn(), removeListener: vi.fn() }));
  global.ResizeObserver = class { observe() {} unobserve() {} disconnect() {} };
});
afterEach(cleanup);
const wrap = ({ children }: { children: ReactNode }) => <MantineProvider>{children}</MantineProvider>;

it("opens four shared checks and retains safe failure detail", async () => {
  render(<DiagnosticContent data={diagnosticFixture()} origin="/console/mirrors/diagnostics" page={vi.fn()} selectSource={id => `?source_id=${id}`} />, { wrapper: wrap });
  fireEvent.click(screen.getByRole("button", { name: "Warehouse: Production to Kafka, Failed. Open four checks." }));
  const drawer = await screen.findByRole("dialog");
  expect(within(drawer).getAllByRole("heading", { level: 3 })).toHaveLength(4);
  expect(within(drawer).getByText("PRODUCTION_UNAVAILABLE")).toBeTruthy();
  expect(within(drawer).getByText(/Check Connect task errors/)).toBeTruthy();
  expect(within(drawer).getAllByText(observed).length).toBeGreaterThan(0);
});

it("opens a Source's four checks from a fleet drill-down without rendering individual paths", async () => {
  const close = vi.fn();
  render(<DiagnosticContent data={diagnosticFixture()} origin="/console/mirrors/diagnostics?source_id=source-2&checks=1"
    page={vi.fn()} selectSource={id => id} showPath={false} initialSource="source-2" closeChecks={close} />, { wrapper: wrap });
  const drawer = await screen.findByRole("dialog");
  expect(within(drawer).getAllByRole("heading", { level: 3 })).toHaveLength(4);
  expect(screen.queryByRole("button", { name: /Production to Kafka, Failed/ })).toBeNull();
  fireEvent.keyDown(drawer, { key: "Escape" });
  await waitFor(() => expect(close).toHaveBeenCalledOnce());
});

it("filters a segment by its own health and preserves the runtime scope", () => {
  const data = createFleetFixture().overview();
  render(<AggregateTopology data={data} scope={{ runtime_id: "capture-01" }} origin="/console/mirrors/diagnostics" />, { wrapper: wrap });
  const failed = screen.getAllByRole("link", { name: /Failed/ });
  expect(failed).toHaveLength(4);
  expect(failed[1].getAttribute("href")).toBe("/console/mirrors/diagnostics?health=failed&segment=production&runtime_id=capture-01");
  expect(failed[1].textContent).toContain(String(data.segments.production.failed));
});

it("pages full assignments separately and shows partial interval coverage", () => {
  const page = vi.fn();
  render(<DiagnosticContent data={diagnosticFixture()} origin="/console/mirrors/diagnostics" page={page} selectSource={id => `?source_id=${id}`} />, { wrapper: wrap });
  fireEvent.click(screen.getByText("Runtime assignments (4)"));
  expect(screen.getByText("Sequential cycle covers all 12 assigned Sources.")).toBeTruthy();
  fireEvent.click(within(screen.getByRole("group", { name: "Assigned Sources" })).getByRole("button", { name: "Next" }));
  expect(page).toHaveBeenCalledWith("assignment_offset", 8);
  expect(screen.getByRole("link", { name: "source-8" }).getAttribute("href")).toBe("?source_id=source-8");
  expect(screen.getAllByText("0 / 3 sampled · 3 missing")).toHaveLength(2);
});

it("keeps historical outcomes fixed while a refresh failure marks current checks stale", () => {
  const data = diagnosticFixture();
  render(<DiagnosticContent data={data} stale origin="/console/mirrors/diagnostics" page={vi.fn()} selectSource={id => id} />, { wrapper: wrap });
  expect(screen.getByRole("status").textContent).toContain("stale");
  expect(screen.getByRole("button", { name: "Warehouse: Production to Kafka, Stale. Open four checks." })).toBeTruthy();
  expect(screen.getAllByRole("button", { name: `${observed}: Failed. Open round.` })).toHaveLength(1);
  expect(screen.getAllByLabelText("No round observed")).toHaveLength(12);
});

it("uses one zero-based scale and keeps an unpublished estimate with missing samples", () => {
  const data = measurementsFixture();
  data.sample = null;
  data.row_sample = null;
  data.published_generation_id = null;
  render(<MeasurementContent data={data} origin="/console/mirrors/mirror-1" />, { wrapper: wrap });
  expect(screen.getByText("100,000")).toBeTruthy();
  expect(screen.getByText("No copy has been published yet. The Source estimate remains available.")).toBeTruthy();
  expect(screen.getByRole("link", { name: "Open Source diagnostics" }).getAttribute("href")).toContain("source_id=source-1");
});

it("shows observed idle as zero and leaves unverified freshness unavailable", () => {
  const data = measurementsFixture();
  data.sample!.captured_events = 0;
  data.sample!.committed_events = 0;
  render(<MeasurementContent data={data} origin="/console/mirrors/mirror-1" />, { wrapper: wrap });
  expect(screen.getAllByText("0")).toHaveLength(2);
  expect(screen.getByText("Verified end-to-end freshness").parentElement?.parentElement?.textContent).toContain("Unavailable");
});

it("retains failed refresh data but removes observations after access revocation", async () => {
  const fetch = vi.fn().mockResolvedValueOnce({ count: 2 }).mockRejectedValueOnce(new Error("offline"))
    .mockRejectedValueOnce(new ApiError(403, "AUTH_FORBIDDEN", ""));
  const { result } = renderHook(() => useDiagnosticRead("scope", fetch));
  await waitFor(() => expect(result.current.value).toEqual({ count: 2 }));
  await act(() => result.current.refresh());
  expect(result.current.stale).toBe(true);
  expect(result.current.value).toEqual({ count: 2 });
  await act(() => result.current.refresh());
  expect(result.current.status).toBe("forbidden");
  expect(result.current.value).toBeNull();
});
