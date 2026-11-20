/** @vitest-environment jsdom */
import { createElement, type ReactNode } from "react";
import { act, cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";
import { MirrorDetail } from "./MirrorDetail";
import { presentProblemNotification } from "@/components/feedback/presentProblemNotification";
import { ApiError } from "@/lib/api";

const state = vi.hoisted(() => ({ write: true, dataRead: true, get: vi.fn(), recover: vi.fn(), enabled: vi.fn(), version: vi.fn(), translate: (key: string) => key }));
vi.mock("@/features/channels/api", () => ({ getVersion: state.version }));
vi.mock("./api", () => ({ getMirror: state.get, requestRecovery: state.recover, setMirrorEnabled: state.enabled }));
vi.mock("@refinedev/core", () => ({ useTranslate: () => state.translate, usePermissions: () => ({ data: state.dataRead ? ["sources:data_read"] : [] }), useCan: () => ({ data: { can: state.write } }) }));
vi.mock("@/components/layout/PageChrome", () => ({ PageChrome: ({ children, actions }: { children: ReactNode; actions: ReactNode }) => createElement("main", null, actions, children) }));
vi.mock("@/components/layout/HeaderActions", () => ({ HeaderActions: ({ navigation, lifecycle }: { navigation: ReactNode; lifecycle: ReactNode }) => createElement("div", null, navigation, lifecycle) }));
vi.mock("@/components/navigation/ConsoleLink", () => ({ ConsoleLink: ({ children, href }: { children: ReactNode; href: string }) => createElement("a", { href }, children) }));
vi.mock("@/components/display/DisplayField", () => ({ DisplayField: ({ label, value }: { label: ReactNode; value: ReactNode }) => createElement("div", null, label, createElement("span", null, value)) }));
vi.mock("@/components/display/Instant", () => ({ Instant: ({ value }: { value: string }) => value }));
vi.mock("@/components/form/FormSection", () => ({ FormSection: ({ children, title, description }: { children: ReactNode; title: string; description: string }) => createElement("section", null, title, description, children) }));
vi.mock("@/components/form/TextField", () => ({ TextField: ({ label, editable: _, ...props }: { label: string; editable: boolean }) => createElement("input", { "aria-label": label, ...props }) }));
vi.mock("@/components/form/NumberField", () => ({ NumberField: () => null }));
vi.mock("@/components/feedback/ConfirmActionModal", () => ({ ConfirmActionModal: ({ opened, children, onConfirm, confirmDisabled }: { opened: boolean; children: ReactNode; onConfirm: () => void; confirmDisabled: boolean }) => opened ? createElement("div", { role: "dialog" }, children, createElement("button", { disabled: confirmDisabled, onClick: onConfirm }, "confirm")) : null }));
vi.mock("@/components/feedback/useConsoleMutation", () => ({ useConsoleMutation: () => ({ submitting: false, run: vi.fn(), dialog: null }) }));
vi.mock("@/components/feedback/presentProblemNotification", () => ({ presentProblemNotification: vi.fn() }));
vi.mock("@mantine/core", () => ({
  Stack: ({ children }: { children: ReactNode }) => createElement("div", null, children),
  Text: ({ children }: { children: ReactNode }) => createElement("span", null, children),
  Button: ({ children, onClick, disabled }: { children: ReactNode; onClick: () => void; disabled: boolean }) => createElement("button", { onClick, disabled }, children),
}));

const mirror = { id: "m1", source_id: "source-1", qualified_table: "public.orders", enabled: false, status: "disable_pending", published_generation_id: null, capture_generation: "capture-1", history_epoch: 7, published_reference_count: 2, readiness: [{ key: "ownership", result: "unknown", expected: "exclusion proof", observed: null, observed_at: null, owner: "deployer", action: "Confirm fence" }], control: { stop_ack: null }, progress: null, profile: { state: "unverified" }, fault: null };
afterEach(() => { cleanup(); state.write = true; state.dataRead = true; vi.clearAllMocks(); });
it("keeps unknown readiness and unconfirmed disable visible without fabricated progress", async () => {
  state.get.mockResolvedValue({ mirror });
  render(createElement(MirrorDetail, { id: "m1" }));
  expect(await screen.findByText("mirrors.status.disable_pending")).toBeTruthy();
  expect(screen.getByText("mirrors.result.unknown")).toBeTruthy();
  expect(screen.getAllByText("mirrors.unknownEvidence").length).toBeGreaterThan(0);
  expect(screen.getByRole("button", { name: "mirrors.enable" }).hasAttribute("disabled")).toBe(true);
});
it("sends the epoch captured when recovery opened and a required reason, then shows pending", async () => {
  state.get.mockResolvedValue({ mirror });
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
  state.get.mockResolvedValue({ mirror });
  render(createElement(MirrorDetail, { id: "m1" }));
  await screen.findByText("public.orders");
  expect(screen.queryByRole("button", { name: "mirrors.recovery.retry" })).toBeNull();
  expect(screen.queryByRole("button", { name: "mirrors.enable" })).toBeNull();
});

it("leads a waiting mirror with its published copy and unknown freshness", async () => {
  state.get.mockResolvedValue({ mirror: { ...mirror, status: "waiting", published_generation_id: "g1", readiness: [] } });
  render(createElement(MirrorDetail, { id: "m1" }));
  expect(await screen.findByText("mirrors.event.published")).toBeTruthy();
  expect(screen.getByText("mirrors.freshnessUnknown")).toBeTruthy();
});

it("removes private detail and an open recovery confirmation after access is revoked", async () => {
  const { ApiError } = await import("@/lib/api");
  state.get.mockResolvedValueOnce({ mirror }).mockRejectedValueOnce(new ApiError(403, "AUTH_FORBIDDEN", ""));
  render(createElement(MirrorDetail, { id: "m1" }));
  fireEvent.click(await screen.findByRole("button", { name: "mirrors.recovery.retry" }));
  expect(screen.getByRole("dialog")).toBeTruthy();
  fireEvent.click(screen.getByRole("button", { name: "common.refresh" }));
  await waitFor(() => expect(screen.queryByText("public.orders")).toBeNull());
  expect(screen.queryByRole("dialog")).toBeNull();
});

it.each([[true, true], [false, true], [true, false]])("verifies the Channel reference (%s) and data read permission (%s)", async (current, canRead) => {
  state.dataRead = canRead;
  state.get.mockResolvedValue({ mirror: { ...mirror, object_id: "orders", enabled: true, published_generation_id: "old",
    control: { control_revision: 2 }, operations: [{ kind: "open", state: "pending", control_revision: 2 }] } });
  state.version.mockResolvedValue({ version: { channel_id: "sales", number: 3,
    mirror_bindings: [{ mirror_id: "m1", object_id: "orders", source_id: "source-1", current_reference: current, node_ids: ["read"] }],
    graph: { nodes: [{ id: "read", name: "Orders read", type: "read.mirror", config: { object_id: "orders", freshness_policy: "skip" } }] } } });
  render(createElement(MirrorDetail, { id: "m1", channelId: "sales", version: 3 }));
  await waitFor(() => expect(state.version).toHaveBeenCalledWith("sales", 3));
  if (current) {
    expect((await screen.findByRole("link", { name: "mirrors.backChannel" })).getAttribute("href")).toBe("/console/channels/sales");
    expect(screen.getByText(/Orders read · mirrors.policy.skip/)).toBeTruthy();
    expect(!!screen.queryByText("channels.verify.run")).toBe(canRead);
  } else {
    expect(screen.queryByText("mirrors.backChannel")).toBeNull();
    expect(screen.queryByText("channels.verify.run")).toBeNull();
  }
});

it("offers a retry for a failed version lookup and hides a subsequently denied reference", async () => {
  state.get.mockResolvedValue({ mirror });
  state.version.mockRejectedValueOnce(new Error("Offline")).mockRejectedValueOnce(new ApiError(403, "AUTH_FORBIDDEN", ""));
  render(createElement(MirrorDetail, { id: "m1", channelId: "sales", version: 3 }));
  await waitFor(() => expect(presentProblemNotification).toHaveBeenCalledTimes(1));
  const retry = vi.mocked(presentProblemNotification).mock.calls[0][2]?.onRetry;
  expect(retry).toBeTypeOf("function");
  await act(async () => retry!());
  expect(state.version).toHaveBeenCalledTimes(2);
  expect(presentProblemNotification).toHaveBeenCalledTimes(1);
  expect(screen.queryByRole("link", { name: "mirrors.backChannel" })).toBeNull();
});
