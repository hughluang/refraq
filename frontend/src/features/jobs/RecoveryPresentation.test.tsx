/** @vitest-environment jsdom */

import { MantineProvider } from "@mantine/core";
import { cleanup, fireEvent, render, screen, within } from "@testing-library/react";
import { afterEach, beforeEach, expect, it, vi } from "vitest";

import { JobList } from "@/features/jobs/JobList";
import { ScheduleJobsModal } from "@/features/schedules/ScheduleJobsModal";
import { ScheduleRunStrip } from "@/features/schedules/ScheduleRunStrip";
import { useSessionStore, resetSessionStoreForTests } from "@/providers/session-store";

const state = vi.hoisted(() => ({ items: [] as Record<string, unknown>[] }));
vi.mock("@refinedev/core", () => ({ useTranslate: () => (key: string) => key, useNotification: () => ({ open: vi.fn() }) }));
vi.mock("@/components/layout/PageChrome", () => ({ PageChrome: ({ children }: { children: React.ReactNode }) => <div>{children}</div> }));
vi.mock("@/hooks/useConsolePagedList", () => ({ useConsolePagedList: () => ({ items: state.items, total: state.items.length, page: 1, pageSize: 50, setPage: vi.fn(), reload: vi.fn(), presentation: "ready" }) }));
vi.mock("@/hooks/useListQuery", () => ({ useListQuery: () => ({ page: 1, setPage: vi.fn() }) }));
vi.mock("@/features/jobs/JobDetailModal", () => ({ JobDetailModal: () => null }));
vi.mock("@/features/jobs/JobCancelButton", () => ({ JobCancelButton: () => null }));
vi.mock("@/components/display/RowActions", () => ({ RowActions: () => <button>View</button> }));

const recovered = {
  id: "recovery", kind: "channel_run", summary: "Recovered run", status: "cancelled",
  is_delayed_recovery: true, scheduled_for: "2026-11-17T08:46:00Z",
  created_at: "2026-11-17T08:51:00Z", started_at: null, finished_at: null,
  error_code: null, trigger_kind: "schedule", trigger_ref: "schedule",
};

beforeEach(() => {
  Object.defineProperty(window, "matchMedia", { writable: true, value: () => ({ matches: false, addEventListener: vi.fn(), removeEventListener: vi.fn() }) });
  globalThis.ResizeObserver = class { observe() {} unobserve() {} disconnect() {} };
  useSessionStore.setState({ user: { locale: "en-US", display_timezone: "Asia/Shanghai" } as never });
  state.items = [recovered, { ...recovered, id: "normal", summary: "Normal run", is_delayed_recovery: false, started_at: "2026-11-17T08:53:20Z" }];
});
afterEach(() => { cleanup(); resetSessionStoreForTests(); });

it.each(["global", "schedule"])("shows recovery independently of status and two truthful time rows in the %s list", (surface) => {
  render(<MantineProvider env="test">{surface === "global" ? <JobList /> : <ScheduleJobsModal opened scheduleId="schedule" onClose={vi.fn()} />}</MantineProvider>);
  expect(screen.getAllByText("jobs.delayedRecovery")).toHaveLength(1);
  expect(screen.getByText("jobs.fields.time")).toBeTruthy();
  const row = screen.getByText("Recovered run").closest("tr")!;
  expect(within(row).getByText("jobs.fields.created: 11/17/2026, 4:51:00 PM")).toBeTruthy();
  expect(within(row).getByText("jobs.fields.started: jobs.notStarted")).toBeTruthy();
  expect(screen.getByText("jobs.fields.started: 11/17/2026, 4:53:20 PM")).toBeTruthy();
  expect(within(row).queryByText(/4:46:00/)).toBeNull();
  expect(within(row).getByText("status.job.cancelled")).toBeTruthy();
});

it.each([true, false])("opens the run-strip tooltip by keyboard with recovery=%s and all three times", (recovery) => {
  render(<MantineProvider env="test"><ScheduleRunStrip jobs={[{ ...recovered, is_delayed_recovery: recovery }]} onOpenJobs={vi.fn()} /></MantineProvider>);
  fireEvent.focus(screen.getByLabelText(`status.job.cancelled${recovery ? " · jobs.delayedRecovery" : ""}`));
  const tooltip = screen.getByRole("tooltip");
  expect(tooltip.textContent).toContain("jobs.fields.scheduled: 11/17/2026, 4:46:00 PM");
  expect(tooltip.textContent).toContain("jobs.fields.created: 11/17/2026, 4:51:00 PM");
  expect(tooltip.textContent).toContain("jobs.fields.started: jobs.notStarted");
  expect(tooltip.textContent).toContain("jobs.fields.duration: —");
  expect(within(tooltip).queryByText("jobs.delayedRecovery") !== null).toBe(recovery);
});
