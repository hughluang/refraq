/** @vitest-environment jsdom */
import { createElement, type ReactNode } from "react";
import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";
import { MirrorDetail } from "./MirrorDetail";
import { presentProblemNotification } from "@/components/feedback/presentProblemNotification";
import { ApiError } from "@/lib/api";
vi.mock("./MirrorMeasurements", () => ({ MirrorMeasurements: () => null }));

const state = vi.hoisted(() => ({ write: true, get: vi.fn(), recover: vi.fn(), enabled: vi.fn(), remove: vi.fn(), older: vi.fn(), replace: vi.fn(), translate: ((key: string, _params?: Record<string, unknown>) => key) as (key: string, params?: Record<string, unknown>) => string }));
vi.mock("./api", () => ({ getMirror: state.get, requestRecovery: state.recover, setMirrorEnabled: state.enabled, deleteMirror: state.remove, getJournalPage: state.older }));
vi.mock("@/components/navigation/useConsoleNavigation", () => ({
  useConsoleLocation: () => ({ href: "/console/mirrors/m1", search: new URLSearchParams() }),
  useConsoleNavigation: () => ({ replace: state.replace }),
}));
vi.mock("@refinedev/core", () => ({ useTranslate: () => state.translate, useCan: () => ({ data: { can: state.write } }) }));
vi.mock("@/components/layout/PageChrome", () => ({ PageChrome: ({ children, actions, title, titleExtra, description }: { children: ReactNode; actions: ReactNode; title: string; titleExtra: ReactNode; description?: string }) => createElement("main", null, createElement("h1", null, title), description && createElement("p", null, description), titleExtra, actions, children) }));
vi.mock("@/components/layout/HeaderActions", () => ({ HeaderActions: ({ navigation, lifecycle, standard }: { navigation: ReactNode; lifecycle: ReactNode; standard: ReactNode }) => createElement("div", null, navigation, lifecycle, standard) }));
vi.mock("@/components/navigation/ConsoleLink", () => ({ ConsoleLink: ({ children, href }: { children: ReactNode; href: string }) => createElement("a", { href }, children) }));
vi.mock("@/components/display/StatusBadge", () => ({ StatusBadge: ({ labelKey, freshness }: { labelKey: string; freshness: { onRefresh: () => void; updatedAt: string } }) =>
  createElement("button", { onClick: freshness.onRefresh, title: freshness.updatedAt }, labelKey) }));
vi.mock("@/providers/notification-provider", () => ({ presentConsoleNotification: vi.fn() }));
vi.mock("@/components/display/DisplayField", () => ({ DisplayField: ({ label, value }: { label: ReactNode; value: ReactNode }) => createElement("div", null, label, createElement("span", null, value)) }));
vi.mock("@/components/display/Instant", () => ({ Instant: ({ value }: { value: string }) => value }));
vi.mock("@/components/form/FormSection", () => ({ FormSection: ({ children, title, description }: { children: ReactNode; title: string; description: string }) => createElement("section", null, title, description, children) }));
vi.mock("@/components/form/TextField", () => ({ TextField: ({ label, editable: _, ...props }: { label: string; editable: boolean }) => createElement("input", { "aria-label": label, ...props }) }));
vi.mock("@/components/feedback/ConfirmActionModal", () => ({ ConfirmActionModal: ({ opened, children, onConfirm, confirmDisabled }: { opened: boolean; children: ReactNode; onConfirm: () => void; confirmDisabled: boolean }) => opened ? createElement("div", { role: "dialog" }, children, createElement("button", { disabled: confirmDisabled, onClick: onConfirm }, "confirm")) : null }));
vi.mock("@/components/feedback/useConsoleMutation", () => ({ useConsoleMutation: () => ({ submitting: false, run: vi.fn(), dialog: null }) }));
vi.mock("@/components/feedback/presentProblemNotification", () => ({ presentProblemNotification: vi.fn() }));
vi.mock("@mantine/core", () => ({
  Switch: ({ label, checked, disabled, onChange }: { label: string; checked: boolean; disabled: boolean; onChange: () => void }) => createElement("input", { type: "checkbox", role: "switch", "aria-label": label, checked, disabled, onChange }),
  Stack: ({ children }: { children: ReactNode }) => createElement("div", null, children),
  Text: ({ children }: { children: ReactNode }) => createElement("span", null, children),
  Button: ({ children, onClick, disabled }: { children: ReactNode; onClick: () => void; disabled: boolean }) => createElement("button", { onClick, disabled }, children),
}));

const mirror = {
  id: "m1", source_id: "source-1", source_name: "Sales", source_engine: "mysql", qualified_table: "public.orders",
  storage_destination: "source_mirror", source_size_bytes: null, estimated_rows: null,
  enabled: false, status: "disable_pending", published_generation_id: null, capture_generation: "capture-1", history_epoch: 7,
  readiness: [{ key: "ownership", result: "unknown", expected: "exclusion proof", observed: null,
    observed_at: null, owner: "deployer", action: "Confirm fence" }],
  control: { stop_ack: null }, progress: null, profile: { state: "unverified" }, fault: null, operations: [],
};
afterEach(() => { cleanup(); state.write = true; state.translate = (key) => key; vi.clearAllMocks(); });
it("keeps unknown readiness and unconfirmed disable visible without fabricated progress", async () => {
  state.get.mockResolvedValue({ mirror, can_enable: true });
  render(createElement(MirrorDetail, { id: "m1" }));
  expect(await screen.findByText("mirrors.status.disable_pending")).toBeTruthy();
  expect(screen.getByText("mirrors.result.unknown")).toBeTruthy();
  expect(screen.getAllByText("mirrors.unknownEvidence").length).toBeGreaterThan(0);
  expect(screen.getByRole("switch", { name: "mirrors.synchronization" }).hasAttribute("disabled")).toBe(false);
});
it("names the Source engine in the mirror origin instead of a fixed engine", async () => {
  state.translate = (key, params) => key === "sources.engines.mysql" ? "MySQL"
    : key === "mirrors.sourceToStorage" ? `${params?.source} · ${params?.engine} → ${params?.destination}` : key;
  state.get.mockResolvedValue({ mirror, can_enable: true });
  render(createElement(MirrorDetail, { id: "m1" }));
  expect(await screen.findByText("Sales · MySQL → source_mirror")).toBeTruthy();
});
it("confirms a stop only when refreshed evidence matches the current disable operation", async () => {
  const observedAt = "2026-01-02T03:04:05Z";
  const stopped = {
    ...mirror,
    status: "disabled",
    published_generation_id: "g1",
    control: {
      control_revision: 2,
      applied_revision: 2,
      observed_at: observedAt,
      stop_ack: { operation_id: "old-disable", source_operation_id: "source-stop", observed_at: observedAt },
    },
    operations: [{
      id: "current-disable", mirror_id: "m1", kind: "disable", state: "applied", control_revision: 2,
      observed_evidence_refs: ["source-stop"], requested_at: "2026-01-02T03:00:00Z",
    }],
  };
  state.get.mockResolvedValueOnce({ mirror: stopped, can_enable: true }).mockResolvedValueOnce({
    can_enable: true,
    mirror: { ...stopped, control: { ...stopped.control, stop_ack: { ...stopped.control.stop_ack, operation_id: "current-disable" } } },
  });
  render(createElement(MirrorDetail, { id: "m1" }));
  await screen.findByText("mirrors.event.published");
  expect(screen.getByText("mirrors.event.disableRequested")).toBeTruthy();
  expect(screen.queryByText("mirrors.event.stopConfirmed")).toBeNull();
  expect(screen.getByRole("switch", { name: "mirrors.synchronization" }).hasAttribute("disabled")).toBe(false);

  fireEvent.click(screen.getByRole("button", { name: "common.refresh" }));
  expect(await screen.findByText("mirrors.event.stopConfirmed", { exact: false })).toBeTruthy();
  expect(screen.queryByText("mirrors.event.disableRequested")).toBeNull();
  expect(screen.getByRole("switch", { name: "mirrors.synchronization" }).hasAttribute("disabled")).toBe(false);
});
it("sends the epoch captured when recovery opened and a required reason, then shows pending", async () => {
  state.get.mockResolvedValue({ mirror, can_enable: true });
  state.recover.mockResolvedValue({ operation_id: "op-7", state: "pending" });
  render(createElement(MirrorDetail, { id: "m1" }));
  fireEvent.click(await screen.findByRole("button", { name: "mirrors.recovery.run_now" }));
  expect(screen.getByRole("button", { name: "confirm" }).hasAttribute("disabled")).toBe(true);
  fireEvent.change(screen.getByRole("textbox", { name: "mirrors.reason" }), { target: { value: "Approved recovery window" } });
  fireEvent.click(screen.getByRole("button", { name: "confirm" }));
  await waitFor(() => expect(state.recover).toHaveBeenCalledWith("m1", { action: "run_now", expected_history_epoch: 7, reason: "Approved recovery window" }));
  expect(await screen.findByText("op-7: mirrors.pending")).toBeTruthy();
});
it("hides all lifecycle writes from read-only operators", async () => {
  state.write = false;
  state.get.mockResolvedValue({ mirror, can_enable: true });
  render(createElement(MirrorDetail, { id: "m1" }));
  await screen.findByText("public.orders");
  expect(screen.queryByRole("button", { name: "mirrors.recovery.retry" })).toBeNull();
  expect(screen.getByRole("switch", { name: "mirrors.synchronization" }).hasAttribute("disabled")).toBe(true);
});

it("leads a waiting mirror with its published copy and unknown freshness", async () => {
  state.get.mockResolvedValue({ mirror: { ...mirror, status: "waiting", published_generation_id: "g1", readiness: [] } });
  render(createElement(MirrorDetail, { id: "m1" }));
  expect(await screen.findByText("mirrors.event.published")).toBeTruthy();
  expect(screen.getByText("mirrors.freshnessUnknown")).toBeTruthy();
});

it("removes private detail and an open recovery confirmation after access is revoked", async () => {
  state.get.mockResolvedValueOnce({ mirror: { ...mirror, enabled: true, can_retry: true, status: "needs_attention" } }).mockRejectedValueOnce(new ApiError(403, "AUTH_FORBIDDEN", ""));
  render(createElement(MirrorDetail, { id: "m1" }));
  fireEvent.click(await screen.findByRole("button", { name: "mirrors.recovery.retry" }));
  expect(screen.getByRole("dialog")).toBeTruthy();
  fireEvent.click(screen.getByRole("button", { name: "common.refresh" }));
  await waitFor(() => expect(screen.queryByText("public.orders")).toBeNull());
  expect(screen.queryByRole("dialog")).toBeNull();
});

it("keeps a completed scan in catch-up until the Open has a verified publication", async () => {
  state.get.mockResolvedValue({
    mirror: {
      ...mirror, enabled: true, status: "catching_up", control: { control_revision: 1 }, readiness: [],
      operations: [{ id: "open-1", kind: "open", state: "pending", control_revision: 1 }],
      progress: { stage: "catching_up", scan_complete: true, scanned_bytes: null, scan_percent: 100 },
    },
  });
  render(createElement(MirrorDetail, { id: "m1" }));
  await screen.findByText("100%");
  expect(screen.getByRole("progressbar").getAttribute("value")).toBe("100");
  expect(screen.getByText("mirrors.scanBytesUnavailable")).toBeTruthy();
  expect(screen.getByText("mirrors.awaitingPublication")).toBeTruthy();
  expect(screen.getByText("mirrors.noCopy")).toBeTruthy();
  expect(screen.getByText(/mirrors.phase.catchup/).closest("li")?.getAttribute("aria-current")).toBe("step");
  expect(screen.queryByText("mirrors.event.published")).toBeNull();
});

it("follows the replacement Open through publication within the same control revision", async () => {
  const operation = { kind: "open", control_revision: 3 };
  const previous = [
    { ...operation, id: "old-attempt", state: "superseded" },
    { ...operation, id: "first-copy", state: "applied" },
  ];
  const replacement = { ...operation, id: "replacement", state: "pending" };
  const building = {
    ...mirror, enabled: true, published_generation_id: "g1", control: { control_revision: 3 }, readiness: [],
    operations: [...previous, replacement],
  };
  state.get.mockResolvedValueOnce({ mirror: building }).mockResolvedValue({
    mirror: { ...building, published_generation_id: "g2", operations: [...previous, { ...replacement, state: "applied" }] },
  });
  render(createElement(MirrorDetail, { id: "m1" }));

  const request = await screen.findByText("mirrors.openRequest");
  expect(within(request).getByText("replacement")).toBeTruthy();
  expect(within(request).getByText("mirrors.awaitingPublication")).toBeTruthy();
  expect(screen.getByText(/mirrors.phase.admission/).closest("li")?.getAttribute("aria-current")).toBe("step");

  fireEvent(document, new Event("visibilitychange"));
  expect(await within(request).findByText("mirrors.openApplied")).toBeTruthy();
  expect(within(request).getByText("replacement")).toBeTruthy();
  expect(screen.getByText(/mirrors.phase.publish/).closest("li")?.textContent).toContain("mirrors.phase.complete");
});

it.each([null, "2026-01-01T02:00:00Z"])("shows the byte count with its own observation time (%s)", async (observedAt) => {
  state.get.mockResolvedValue({ mirror: {
    ...mirror, enabled: true, readiness: [], control: { control_revision: 1 },
    operations: [{ id: "open-1", kind: "open", state: "pending", control_revision: 1 }],
    progress: { stage: "scan", observed_at: "2026-01-01T03:00:00Z", scanned_bytes: 0,
      bytes_observed_at: observedAt, byte_notification_offset: observedAt ? 14 : null, scan_percent: 0 },
  } });
  render(createElement(MirrorDetail, { id: "m1" }));
  const sample = await screen.findByText(/mirrors.bytesObservedAt/);
  expect(sample.textContent).toContain(observedAt ?? "mirrors.unknownEvidence");
  expect(screen.getByRole("progressbar").getAttribute("value")).toBe("0");
});

it("keeps the last observed Mirror on a failed poll and recovers on the next visible poll", async () => {
  const active = { ...mirror, enabled: true, control: { control_revision: 1 }, status: "waiting",
    operations: [{ id: "open-1", kind: "open", state: "pending", control_revision: 1 }] };
  state.get.mockResolvedValueOnce({ mirror: active }).mockRejectedValueOnce(new Error("temporary outage"))
    .mockResolvedValue({ mirror: { ...active, status: "ready", published_generation_id: "g-new",
      operations: [{ ...active.operations[0], state: "applied" }] } });
  render(createElement(MirrorDetail, { id: "m1" }));
  await screen.findByText("mirrors.status.waiting");
  fireEvent(document, new Event("visibilitychange"));
  const marker = await screen.findByRole("button", { name: "mirrors.refreshStale" });
  expect(Date.parse(marker.title)).toBeGreaterThan(0);
  expect(screen.getByText("mirrors.noCopy")).toBeTruthy();
  expect(presentProblemNotification).not.toHaveBeenCalled();
  fireEvent(document, new Event("visibilitychange"));
  expect(await screen.findByText("mirrors.readableCopy")).toBeTruthy();
  expect(screen.queryByText("mirrors.refreshStale")).toBeNull();
});

it("forgets the last successful read across access loss and a subsequent transient error", async () => {
  state.get.mockResolvedValueOnce({ mirror }).mockRejectedValueOnce(new ApiError(403, "AUTH_FORBIDDEN", ""))
    .mockRejectedValueOnce(new Error("outage"));
  render(createElement(MirrorDetail, { id: "m1" }));
  await screen.findByText("public.orders");
  const refresh = screen.getByRole("button", { name: "common.refresh" });
  fireEvent.click(refresh);
  await waitFor(() => expect(screen.queryByText("public.orders")).toBeNull());
  fireEvent.click(refresh);
  await waitFor(() => expect(presentProblemNotification).toHaveBeenCalledTimes(2));
  expect(screen.queryByText("public.orders")).toBeNull();
});

it.each([
  ["snapshot_window_closed", "scan", "queued"], ["publication_pending", "scan", "queued"],
  ["capture_credential_missing", "admission", "blocked"], ["incremental_snapshot_blocked", "scan", "blocked"],
])("explains %s at the evidenced phase", async (reason, phase, disposition) => {
  const admitted = reason !== "capture_credential_missing";
  state.get.mockResolvedValue({ mirror: {
    ...mirror, enabled: true, status: "waiting", control: { control_revision: 1 },
    operations: [{ id: "open", kind: "open", state: "pending", control_revision: 1 }],
    readiness: [{ key: "capture_admission", result: admitted ? "pass" : "unknown" }, { key: reason, result: "fail" }],
    publication_wait: reason === "publication_pending" ? { mirror_id: "sibling", qualified_table: "public.invoices" } : null,
  } });
  render(createElement(MirrorDetail, { id: "m1" }));
  const step = (await screen.findByText(`mirrors.phase.${phase}`)).closest("li")!;
  expect(step.getAttribute("aria-current")).toBe("step");
  expect(within(step).getByText(`mirrors.phase.${disposition}`)).toBeTruthy();
  if (reason === "publication_pending") {
    expect(screen.getByRole("link", { name: "public.invoices" }).getAttribute("href")).toContain("/console/mirrors/sibling?");
    expect(screen.queryByText("mirrors.wait.snapshot_slot_busy")).toBeNull();
  }
});

it("keeps requests and technical receipts collapsed when polling updates detail", async () => {
  state.get.mockResolvedValue({ mirror });
  render(createElement(MirrorDetail, { id: "m1" }));
  const disclosure = (await screen.findByText("mirrors.requestsAndReceipts")).closest("details")!;
  expect(disclosure.open).toBe(false);
  disclosure.open = true;
  fireEvent.click(screen.getByRole("button", { name: "common.refresh" }));
  await waitFor(() => expect(state.get).toHaveBeenCalledTimes(2));
  expect(disclosure.open).toBe(true);
});

it("keeps the Open waiting for continuity after an inconclusive Retry and pages the UTC journal", async () => {
  const event = (kind: string, category: string, at: string, id: string, op: string) => ({
    kind, category, at, id, operation_id: op, control_revision: 3, history_epoch: "h1", generation_id: "g1",
    outcome: null, outcome_at: null, related_operation_id: null,
  });
  const unknown = event("continuity_unknown", "observation", "2026-03-02T00:03:00Z", "ev-1", "retry-1");
  const retry = { ...event("retry", "request", "2026-03-01T23:58:00Z", "retry-1", "retry-1"),
    outcome: "continuity_unknown", outcome_at: unknown.at };
  const open = { ...event("resume", "request", "2026-03-01T22:00:00Z", "open", "open"),
    outcome: "awaiting_continuity" };
  const record = {
    ...mirror, enabled: true, published_generation_id: "g1", control: { control_revision: 3 },
    operations: [{ id: "open", control_revision: 3, kind: "open", state: "pending" }], open_request: open,
    journal: { items: [unknown, retry, open], next_cursor: open.id }, can_retry: true, latest_request: retry,
    blocker: { cause: "continuity", since: retry.at, last_checked_at: unknown.at },
  };
  state.get.mockResolvedValue({ mirror: record });
  state.older.mockResolvedValue({ items: [event("disable", "request", "2026-02-28T22:00:00Z", "stop", "stop")], next_cursor: null });
  render(createElement(MirrorDetail, { id: "m1" }));
  const journal = await screen.findByRole("region", { name: "mirrors.journalTitle" });
  expect(within(journal).getAllByRole("listitem")).toHaveLength(3);
  expect(within(journal).getAllByRole("heading", { level: 3 }).map(title => title.textContent))
    .toEqual(["2026-03-02 UTC", "2026-03-01 UTC"]);
  expect(within(journal).getAllByRole("listitem")[2].textContent).toContain("mirrors.journal.awaiting_continuity");
  expect(screen.getByRole("button", { name: "mirrors.recovery.retry" })).toBeTruthy();
  fireEvent.click(within(journal).getByRole("button", { name: "mirrors.journal.older" }));
  await within(journal).findByRole("heading", { name: "2026-02-28 UTC" });
  expect(state.older).toHaveBeenCalledWith("m1", "open", expect.any(AbortSignal));
  const late = event("continuity_verified", "observation", "2026-03-01T23:57:00Z", "late", "retry-1");
  state.get.mockResolvedValue({ mirror: { ...record, journal: { items: [unknown, retry, late], next_cursor: late.id } } });
  fireEvent.click(screen.getByRole("button", { name: "common.refresh" }));
  await waitFor(() => expect(screen.getByRole("region", { name: "mirrors.journalTitle" }).querySelectorAll("li")).toHaveLength(3));
  state.older.mockResolvedValue({ items: [open], next_cursor: null });
  fireEvent.click(screen.getByRole("button", { name: "mirrors.journal.older" }));
  await waitFor(() => expect(state.older).toHaveBeenLastCalledWith("m1", "late", expect.any(AbortSignal)));
  expect(await within(screen.getByRole("region", { name: "mirrors.journalTitle" })).findByText("mirrors.journal.awaiting_continuity")).toBeTruthy();
});

it("deletes the confirmed revision and returns to the originating view on completion", async () => {
  state.get.mockResolvedValue({ mirror: { ...mirror, control: { control_revision: 4 }, status: "disabled" } });
  state.remove.mockResolvedValue(undefined);
  render(createElement(MirrorDetail, { id: "m1" }));
  fireEvent.click(await screen.findByRole("button", { name: "mirrors.delete" }));
  expect(state.remove).not.toHaveBeenCalled();
  fireEvent.click(within(screen.getByRole("dialog")).getByRole("button", { name: "confirm" }));
  await waitFor(() => expect(state.replace).toHaveBeenCalledWith("/console/mirrors"));
  expect(state.remove).toHaveBeenCalledWith("m1", 4, expect.any(AbortSignal));
});

it.each([true, false])("uses accepted synchronization state after a failed refresh (enabled=%s)", async (enabled) => {
  const previous = { ...mirror, enabled: !enabled, control: { control_revision: 4 } };
  state.get.mockResolvedValueOnce({ mirror: previous, can_enable: enabled }).mockRejectedValue(new Error("outage"));
  state.enabled.mockResolvedValue({ mirror: { ...previous, enabled, control: { control_revision: 5 } }, operation_id: "toggle-5" });
  render(createElement(MirrorDetail, { id: "m1" }));
  const toggle = await screen.findByRole("switch", { name: "mirrors.synchronization" });
  fireEvent.click(toggle);
  if (!enabled) fireEvent.click(screen.getByRole("button", { name: "confirm" }));
  await waitFor(() => expect(state.enabled).toHaveBeenCalledWith("m1", enabled, expect.any(AbortSignal)));
  await screen.findByRole("button", { name: "mirrors.refreshStale" });
  expect(toggle).toHaveProperty("checked", enabled);
  expect(toggle.hasAttribute("disabled")).toBe(!enabled);
  expect(screen.getByRole("button", { name: "mirrors.delete" }).hasAttribute("disabled")).toBe(true);
  expect(Boolean(screen.queryByText("mirrors.resumePlan"))).toBe(!enabled);
  expect(state.remove).not.toHaveBeenCalled();

  state.get.mockResolvedValue({ mirror: { ...previous, enabled, control: { control_revision: 5 } }, can_enable: !enabled });
  fireEvent.click(screen.getByRole("button", { name: "common.refresh" }));
  await waitFor(() => expect(screen.getByRole("button", { name: "mirrors.delete" }).hasAttribute("disabled")).toBe(false));
  expect(toggle.hasAttribute("disabled")).toBe(false);
});

it.each([
  { can_retry: false },
  { deletion_operation_id: "delete-3" },
])("closes a Retry confirmation when a refresh disallows it (%j)", async (change) => {
  const blocked = { ...mirror, enabled: true, can_retry: true, control: { control_revision: 3 } };
  state.get.mockResolvedValueOnce({ mirror: blocked }).mockResolvedValue({ mirror: { ...blocked, ...change } });
  render(createElement(MirrorDetail, { id: "m1" }));
  fireEvent.click(await screen.findByRole("button", { name: "mirrors.recovery.retry" }));
  expect(screen.getByRole("dialog")).toBeTruthy();
  fireEvent.click(screen.getByRole("button", { name: "common.refresh" }));
  await waitFor(() => expect(state.get).toHaveBeenCalledTimes(2));
  await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());
  expect(state.recover).not.toHaveBeenCalled();
});

it.each(["latest_request", "operations"])("retires the local pending receipt once %s observes it", async (observedIn) => {
  const blocked = { ...mirror, enabled: true, can_retry: true, control: { control_revision: 3 } };
  const request = { id: "retry-3", operation_id: "retry-3", kind: "retry", at: "2026-03-01T23:58:00Z",
    outcome: "continuity_unknown", outcome_at: null };
  state.get.mockResolvedValueOnce({ mirror: blocked }).mockResolvedValue({
    mirror: { ...blocked,
      latest_request: observedIn === "latest_request" ? request : { ...request, id: "retry-other", operation_id: "retry-other" },
      operations: observedIn === "operations" ? [{ id: request.operation_id, kind: "retry", state: "applied", control_revision: 3 }] : [],
    },
  });
  state.recover.mockResolvedValue({ operation_id: request.operation_id, state: "pending" });
  render(createElement(MirrorDetail, { id: "m1" }));
  fireEvent.click(await screen.findByRole("button", { name: "mirrors.recovery.retry" }));
  fireEvent.click(screen.getByRole("button", { name: "confirm" }));
  await screen.findByText("mirrors.journal.continuity_unknown");
  await waitFor(() => expect(screen.queryByText("retry-3: mirrors.pending")).toBeNull());

  state.get.mockResolvedValue({ mirror: { ...blocked, latest_request: { ...request, id: "disable-4", operation_id: "disable-4", kind: "disable" } } });
  fireEvent.click(screen.getByRole("button", { name: "common.refresh" }));
  await screen.findByText("mirrors.journal.disable", { exact: false });
  expect(screen.queryByText("retry-3: mirrors.pending")).toBeNull();
});

it("links a blocked capture admission to the runtime deployment step", async () => {
  state.get.mockResolvedValue({ mirror: {
    ...mirror, enabled: true, source_id: "source-1",
    readiness: [{ key: "capture_admission", result: "unknown", owner: "deployer", action: "Qualify capture before admission",
      expected: null, observed: null, observed_at: null }],
  } });
  render(createElement(MirrorDetail, { id: "m1" }));
  const links = await screen.findAllByRole("link", { name: "mirrorSetup.openStep" });
  expect(links.every(link => link.getAttribute("href") === "/console/mirrors/setup?source_id=source-1&step=runtime")).toBe(true);
  expect(screen.getAllByText("mirrors.confirmCapture").length).toBeGreaterThan(0);
});
