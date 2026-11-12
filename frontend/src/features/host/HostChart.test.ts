/** @vitest-environment jsdom */

import { MantineProvider } from "@mantine/core";
import { act, cleanup, fireEvent, render, screen } from "@testing-library/react";
import { createElement } from "react";
import { afterEach, beforeEach, expect, it, vi } from "vitest";

import { HostChart } from "@/features/host/HostChart";
import en from "@/locales/en-US/common.json";

vi.mock("@refinedev/core", () => ({
  useTranslate: () => (key: string, params?: Record<string, unknown>) => {
    let text = (en as Record<string, string>)[key] ?? key;
    for (const [name, value] of Object.entries(params ?? {})) text = text.replace(`{{${name}}}`, String(value));
    return text;
  },
  useGetLocale: () => () => "en-US",
}));

vi.mock("@/providers/time-zones", () => ({ useTimeZones: () => ({ items: [] }) }));
vi.mock("@/providers/session-store", () => ({
  useSessionStore: (select: (state: unknown) => unknown) => select({ user: { locale: "en-US", display_timezone: "America/New_York" } }),
}));

it("formats observed and keyboard timestamps in the user's display timezone", () => {
  const { container } = chart([{ name: "A", samples: [at(0, 4)] }]);
  expect(container.querySelector("time")?.textContent).toContain("7:00:00 PM");
  fireEvent.click(screen.getByText("Recorded samples", { selector: "summary" }));
  expect(screen.getByRole("slider").getAttribute("aria-valuetext")).toContain("7:00:00 PM");
});

const start = "2026-11-12T00:00:00Z";
const end = "2026-11-12T00:10:00Z";
const at = (minute: number, v: number | null) => ({ t: `2026-11-12T00:${String(minute).padStart(2, "0")}:00Z`, v });

beforeEach(() => {
  vi.stubGlobal("ResizeObserver", class { observe() {} disconnect() {} });
  Object.defineProperty(window, "matchMedia", { writable: true, value: () => ({ matches: false, addEventListener() {}, removeEventListener() {} }) });
});
afterEach(() => { cleanup(); vi.unstubAllGlobals(); });

function chart(series: { name: string; samples: ReturnType<typeof at>[] }[], unit: "number" | "byte-change" | "share" = "number") {
  return render(createElement(MantineProvider, { env: "test" }, createElement(HostChart, {
    title: "Queue", start, end, stepSeconds: 60, unit, series,
  })));
}

it("keeps malformed sample Instants local and never draws invalid coordinates", () => {
  const { container } = chart([{ name: "A", samples: [at(0, 4), { t: "not-an-instant", v: 9 }] }]);
  expect(screen.getByText(new RegExp(en["problems.API_CONTRACT_INVALID"]))).toBeTruthy();
  expect(container.querySelectorAll('[data-series="A"]')).toHaveLength(1);
  expect(container.querySelector('[data-series="A"]')?.getAttribute("cy")).toBe("16");
  expect(container.innerHTML).not.toMatch(/(?:cx|points)="[^"]*NaN/);
  fireEvent.click(screen.getByText("Recorded samples", { selector: "summary" }));
  fireEvent.keyDown(screen.getByRole("slider"), { key: "End" });
  expect(screen.getByRole("slider").getAttribute("aria-valuetext")).toBe(en["problems.API_CONTRACT_INVALID"]);
});

it("keeps an invalid response bound local without plotting invented positions", () => {
  const { container } = render(createElement(MantineProvider, { env: "test" }, createElement(HostChart, {
    title: "Queue", start, end: "invalid", stepSeconds: 60, unit: "number", series: [{ name: "A", samples: [at(0, 4)] }],
  })));
  expect(screen.getAllByText(en["problems.API_CONTRACT_INVALID"]).length).toBeGreaterThan(0);
  expect(container.querySelectorAll("[data-series]")).toHaveLength(0);
  expect(screen.getByText(/Last observed/, { selector: "p" })).toBeTruthy();
});

it("places unequal series on the response timestamp domain and one zero-based y domain", () => {
  const { container } = chart([
    { name: "A", samples: [at(1, 10), at(2, 10)] },
    { name: "B", samples: [at(2, 20), at(3, 10)] },
  ]);
  const lines = [...container.querySelectorAll("polyline[data-series]")];
  expect(lines).toHaveLength(2);
  const points = lines.map((line) => line.getAttribute("points")!.split(" ").map((point) => point.split(",").map(Number)));
  expect(points[0]![1]![0]).toBe(points[1]![0]![0]);
  expect(points[0]![0]![1]).toBe(points[1]![1]![1]);
  expect(points[0]![0]![1]).toBeGreaterThan(points[1]![0]![1]!);
  expect(points[0]![0]![0]).toBeLessThan(200);
  expect(points[0]![1]![0]! - points[0]![0]![0]!).toBeCloseTo(points[1]![1]![0]! - points[1]![0]![0]!, 1);
  expect(points[0]![0]![1]).toBe(96);
  expect(points[1]![0]![1]).toBe(16);
  expect(screen.getByRole("img", { name: "Queue" }).querySelector("desc")?.textContent).toContain("Recorded samples");
});

it("keeps null and missing evaluation steps as gaps with genuine isolated dots", () => {
  const { container } = chart([{ name: "A", samples: [at(0, 2), at(1, null), at(2, 3), at(5, 4), at(6, 4)] }]);
  expect(container.querySelectorAll("circle[data-series]")).toHaveLength(2);
  expect(container.querySelectorAll("polyline[data-series]")).toHaveLength(1);
  expect(container.querySelector("polyline")?.getAttribute("points")?.split(" ")).toHaveLength(2);
});

it("keeps flat magnitude and recorded zeros visible, distinct from all-null absence", () => {
  const { container } = chart([
    { name: "flat", samples: [at(0, 5), at(1, 5)] },
    { name: "zero", samples: [at(0, 0), at(1, 0)] },
    { name: "absent", samples: [at(0, null)] },
  ]);
  const lines = container.querySelectorAll("polyline");
  expect(lines).toHaveLength(2);
  expect(lines[0]?.getAttribute("points")).toContain(",16.00");
  expect(lines[1]?.getAttribute("points")).toContain(",176.00");
  expect(screen.getAllByText("No recorded samples").length).toBeGreaterThan(0);
});

it("exposes signed byte bounds and a meaningful zero", () => {
  const { container } = chart([{ name: "change", samples: [at(0, -1024), at(1, 1024)] }], "byte-change");
  expect(container.querySelector("polyline")?.getAttribute("points")).toContain(",176.00");
  expect(screen.getByText("-1 KiB")).toBeTruthy();
  expect(screen.getByText("0 B")).toBeTruthy();
  expect(screen.getAllByText("+1 KiB").length).toBeGreaterThan(0);
});

it("retains a zero tick when signed bounds are asymmetric", () => {
  chart([{ name: "change", samples: [at(0, -1024), at(1, 3072)] }], "byte-change");
  expect(screen.getByText("0 B")).toBeTruthy();
});

it("shows empty histories explicitly without fabricating sample marks", () => {
  const { container } = chart([{ name: "absent", samples: [at(0, null)] }]);
  expect(container.querySelectorAll("[data-series]")).toHaveLength(0);
  expect(screen.getAllByText("No recorded samples").length).toBeGreaterThan(0);
});

it("measures narrow containers without scaling text and separates crowded time labels", () => {
  let resize: ResizeObserverCallback | undefined;
  vi.stubGlobal("ResizeObserver", class {
    constructor(callback: ResizeObserverCallback) { resize = callback; }
    observe() {}
    disconnect() {}
  });
  const { container } = chart([{ name: "A", samples: [at(0, 0)] }]);
  const labels = container.querySelectorAll<SVGTextElement>("svg text");
  labels.forEach((label) => { label.getBBox = () => ({ width: 80 } as DOMRect); });
  act(() => resize?.([{ target: container.querySelector(".mantine-Stack-root"), contentRect: { width: 280 } } as ResizeObserverEntry], {} as ResizeObserver));
  const plot = screen.getByRole("img", { name: "Queue" });
  expect(plot.hasAttribute("viewBox")).toBe(false);
  expect(plot.getAttribute("height")).toBe("188");
  expect(plot.querySelector("circle[data-series]")?.getAttribute("cx")).toBe("92");
  const axis = container.querySelector<HTMLElement>('[data-axis="time"]')!;
  expect(axis.style.gridTemplateColumns).toBe("minmax(0, 1fr)");
  expect(axis.textContent).toContain("Query snapshot time");
  expect(axis.children).toHaveLength(2);
  expect(plot.textContent).not.toContain("Query snapshot time");
});

it("labels a trailing-null history with its actual last observation timestamp", () => {
  const { container } = chart([{ name: "A", samples: [at(0, 4), at(1, null)] }]);
  expect(screen.getByText(/Last observed in displayed history/, { selector: "p" })).toBeTruthy();
  expect(container.querySelector("time")?.getAttribute("datetime")).toBe(at(0, 4).t);
});

it("provides pointer and keyboard parity through one range stop and a timestamped readout", () => {
  const { container } = chart([{ name: "A", samples: [at(0, 0), at(1, null), at(2, 10)] }]);
  fireEvent.click(screen.getByText("Recorded samples", { selector: "summary" }));
  const range = screen.getByRole("slider", { name: "Sample time" });
  expect(container.querySelectorAll("input")).toHaveLength(1);
  fireEvent.keyDown(range, { key: "ArrowRight" });
  expect(screen.getByText("Value: —")).toBeTruthy();
  fireEvent.keyDown(range, { key: "End" });
  expect(screen.getByText("Value: 10")).toBeTruthy();
  expect(container.querySelector("details time")?.getAttribute("datetime")).toBe(at(2, 10).t);
  fireEvent.pointerMove(screen.getByRole("img", { name: "Queue" }), { clientX: 44 });
  expect(screen.getByText("1. A: 0")).toBeTruthy();
  expect(screen.getByText("Value: 10")).toBeTruthy();
});

it("keeps pointer inspection transient without opening or mounting the keyboard disclosure", () => {
  const { container } = chart([{ name: "A", samples: [at(0, 0), at(1, null)] }]);
  const plot = screen.getByRole("img", { name: "Queue" });
  fireEvent.pointerMove(plot, { clientX: 44 });
  expect(container.querySelector("details")?.open).toBe(false);
  expect(screen.queryByRole("slider")).toBeNull();
  expect(screen.getByText("1. A: 0").closest('[aria-hidden="true"]')).toBeTruthy();
  fireEvent.pointerLeave(plot.parentElement!);
  expect(screen.queryByText("1. A: 0")).toBeNull();
  expect(container.querySelector("details")?.open).toBe(false);
});

it("preserves the selected timestamp across inserted samples and resets when it disappears", () => {
  const view = chart([{ name: "A", samples: [at(0, 0), at(2, 10)] }]);
  fireEvent.click(screen.getByText("Recorded samples", { selector: "summary" }));
  fireEvent.keyDown(screen.getByRole("slider"), { key: "End" });
  const redraw = (samples: ReturnType<typeof at>[]) => view.rerender(createElement(MantineProvider, { env: "test" }, createElement(HostChart, {
    title: "Queue", start, end, stepSeconds: 60, unit: "number", series: [{ name: "A", samples }],
  })));
  redraw([at(0, 0), at(1, null), at(2, 10)]);
  expect(screen.getByText("Value: 10")).toBeTruthy();
  expect((screen.getByRole("slider") as HTMLInputElement).value).toBe("2");
  redraw([at(3, 20), at(4, 30)]);
  expect(screen.getByText("Value: 20")).toBeTruthy();
  expect((screen.getByRole("slider") as HTMLInputElement).value).toBe("0");
});
