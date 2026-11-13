import { describe, expect, it, vi } from "vitest";

import { createLayoutAttempts, type LayoutAttemptAdapter, type LayoutState, type LayoutWork } from "./layoutAttempt";
import type { LayoutResult } from "./graphLayout";

const success: LayoutResult = { status: "laid-out", nodes: [] };
const work: LayoutWork = { input: { nodes: [], edges: [] }, ordered: new Map() };

function harness() {
  const state: LayoutState = { graph: "graph", measurements: "measured", auto: true, ready: true, locked: false };
  const pending: { resolve: (result: LayoutResult) => void; reject: (error: Error) => void }[] = [];
  const adapter = {
    read: () => ({ ...state }),
    prepare: vi.fn(() => work),
    run: vi.fn(() => new Promise<LayoutResult>((resolve, reject) => { pending.push({ resolve, reject }); })),
    apply: vi.fn<LayoutAttemptAdapter["apply"]>(),
    publish: vi.fn<LayoutAttemptAdapter["publish"]>(),
  };
  const owner = createLayoutAttempts(adapter);
  const observe = (overrides = {}) => owner.observe({ topology: "topology", measurements: state.measurements, ready: state.ready, adoptToken: 0, mutable: true, ...overrides });
  return { state, adapter, owner, pending, observe };
}

const settle = async () => { await Promise.resolve(); await Promise.resolve(); };

describe("layout attempts", () => {
  it.each(["resolve", "reject"] as const)("ignores stale A %s without releasing B pending", async (outcome) => {
    const h = harness();
    void h.owner.request();
    void h.owner.request();
    const publications = h.adapter.publish.mock.calls.length;
    if (outcome === "resolve") h.pending[0].resolve(success);
    else h.pending[0].reject(new Error("stale"));
    await settle();
    expect(h.adapter.apply).not.toHaveBeenCalled();
    expect(h.adapter.publish).toHaveBeenCalledTimes(publications);
    h.pending[1].resolve(success);
    await settle();
    expect(h.adapter.apply).toHaveBeenCalledExactlyOnceWith(work, success, true, expect.any(Function));
    expect(h.adapter.publish).toHaveBeenLastCalledWith({ pending: false, error: false });
  });

  it("ignores A after B completes and preserves B error", async () => {
    const h = harness();
    void h.owner.request();
    void h.owner.request();
    h.pending[1].reject(new Error("current"));
    await settle();
    const publications = h.adapter.publish.mock.calls.length;
    h.pending[0].resolve(success);
    await settle();
    expect(h.adapter.publish).toHaveBeenCalledTimes(publications);
    expect(h.adapter.publish).toHaveBeenLastCalledWith({ pending: false, error: true });
    expect(h.adapter.run).toHaveBeenCalledTimes(2);
  });

  it.each(["prepare", "run", "invalid-parent"])("reports %s failure and releases pending", async (failure) => {
    const h = harness();
    if (failure === "prepare") h.adapter.prepare.mockImplementationOnce(() => { throw new Error("prepare"); });
    if (failure === "run") h.adapter.run.mockImplementationOnce(() => { throw new Error("run"); });
    const request = h.owner.request();
    if (failure === "invalid-parent") h.pending[0].resolve({ status: "invalid-parent", nodes: [] });
    await request;
    expect(h.adapter.publish).toHaveBeenLastCalledWith({ pending: false, error: true });
    expect(h.adapter.apply).not.toHaveBeenCalled();
    expect(h.adapter.run.mock.calls.length).toBeLessThanOrEqual(1);
  });

  it("clears the previous failure when starting a new request", async () => {
    const h = harness();
    void h.owner.request();
    h.pending[0].reject(new Error("failure"));
    await settle();
    void h.owner.request();
    expect(h.adapter.publish).toHaveBeenLastCalledWith({ pending: true, error: false });
  });

  it.each(["graph", "measurements"] as const)("rereads live %s even without observe", async (field) => {
    const h = harness();
    void h.owner.request();
    h.state[field] = "changed";
    h.pending[0].resolve(success);
    await settle();
    expect(h.adapter.apply).not.toHaveBeenCalled();
    expect(h.adapter.publish).toHaveBeenLastCalledWith({ pending: false, error: false });
    expect(h.adapter.run).toHaveBeenCalledTimes(1);
  });

  it("captures revision and comparison state after synchronous preparation returns", async () => {
    const h = harness();
    h.adapter.prepare.mockImplementationOnce(() => {
      h.owner.edited();
      h.state.graph = "flushed";
      h.state.measurements = "flushed measurements";
      return work;
    });
    void h.owner.request();
    h.pending[0].resolve(success);
    await settle();
    expect(h.adapter.apply).toHaveBeenCalledTimes(1);
    expect(h.adapter.run).toHaveBeenCalledTimes(1);
  });

  it("does not trigger on configuration edits but retries the latest revision on normal completion", async () => {
    const h = harness();
    h.observe();
    h.owner.edited();
    h.state.graph = "latest configuration";
    h.observe();
    expect(h.adapter.run).toHaveBeenCalledTimes(1);
    h.pending[0].resolve(success);
    await settle();
    expect(h.adapter.apply).not.toHaveBeenCalled();
    expect(h.adapter.run).toHaveBeenCalledTimes(2);
    h.adapter.apply.mockImplementationOnce(() => h.owner.edited());
    h.pending[1].resolve(success);
    await settle();
    expect(h.adapter.apply).toHaveBeenCalledTimes(1);
    expect(h.adapter.apply.mock.calls[0][2]).toBe(false);
    expect(h.adapter.run).toHaveBeenCalledTimes(2);
  });

  it("does not retry an exception after a configuration edit", async () => {
    const h = harness();
    h.observe();
    h.owner.edited();
    h.pending[0].reject(new Error("failure"));
    await settle();
    expect(h.adapter.run).toHaveBeenCalledTimes(1);
    expect(h.adapter.publish).toHaveBeenLastCalledWith({ pending: false, error: true });
  });

  it.each(["geometry", "restore", "adopt", "lock", "unmount"] as const)("invalidates in-flight results and completed RAF credentials on %s", async (reason) => {
    const h = harness();
    void h.owner.request();
    h.pending[0].resolve(success);
    await settle();
    const isCurrent = h.adapter.apply.mock.calls[0][3];
    expect(isCurrent()).toBe(true);
    void h.owner.request();
    h.owner.invalidate(reason);
    const publications = h.adapter.publish.mock.calls.length;
    expect(isCurrent()).toBe(false);
    h.pending[1].resolve(success);
    await settle();
    expect(h.adapter.apply).toHaveBeenCalledTimes(1);
    expect(h.adapter.publish).toHaveBeenCalledTimes(publications);
  });

  it("suppresses restored topology until a new authored edit", () => {
    const h = harness();
    h.owner.invalidate("restore");
    h.observe();
    h.observe({ topology: "redo" });
    expect(h.adapter.run).not.toHaveBeenCalled();
    h.owner.invalidate("geometry");
    h.owner.invalidate("lock");
    h.observe({ topology: "still replay" });
    expect(h.adapter.run).not.toHaveBeenCalled();
    h.owner.edited();
    h.observe({ topology: "authored" });
    expect(h.adapter.run).toHaveBeenCalledTimes(1);
  });

  it("adoption clears replay even when the graph is unchanged", () => {
    const h = harness();
    h.owner.invalidate("restore");
    h.observe();
    h.owner.invalidate("adopt");
    h.observe({ adoptToken: 1 });
    expect(h.adapter.run).toHaveBeenCalledTimes(1);
  });

  it.each(["geometry", "restore", "adopt", "lock", "unmount"] as const)("does not resurrect a queued retry after %s", async (reason) => {
    const h = harness();
    h.observe();
    h.owner.edited();
    h.pending[0].resolve(success);
    queueMicrotask(() => h.owner.invalidate(reason));
    await settle();
    expect(h.adapter.run).toHaveBeenCalledTimes(1);
  });

  it.each(["ready", "auto", "locked"] as const)("checks live %s before running a queued retry", async (field) => {
    const h = harness();
    h.observe();
    h.owner.edited();
    h.pending[0].resolve(success);
    queueMicrotask(() => { h.state[field] = field === "locked"; });
    await settle();
    expect(h.adapter.run).toHaveBeenCalledTimes(1);
  });

  it("restarts after StrictMode cleanup without reviving the old completion", async () => {
    const h = harness();
    h.observe();
    h.owner.invalidate("unmount");
    h.observe();
    expect(h.adapter.run).toHaveBeenCalledTimes(2);
    h.pending[0].resolve(success);
    await settle();
    expect(h.adapter.apply).not.toHaveBeenCalled();
    h.pending[1].resolve(success);
    await settle();
    expect(h.adapter.apply).toHaveBeenCalledTimes(1);
  });

  it("does not start while locked and checks the lock again on completion", async () => {
    const h = harness();
    h.state.locked = true;
    await h.owner.request();
    h.observe();
    expect(h.adapter.run).not.toHaveBeenCalled();
    h.state.locked = false;
    void h.owner.request();
    h.state.locked = true;
    h.pending[0].resolve(success);
    await settle();
    expect(h.adapter.apply).not.toHaveBeenCalled();
  });

  it("observes only trigger facts, not output frame geometry", async () => {
    const h = harness();
    h.observe();
    h.adapter.apply.mockImplementationOnce(() => { h.state.graph = "derived frame placement"; h.owner.edited(); });
    h.pending[0].resolve(success);
    await settle();
    h.observe();
    expect(h.adapter.run).toHaveBeenCalledTimes(1);
    h.state.measurements = "ordinary node changed";
    h.observe();
    expect(h.adapter.run).toHaveBeenCalledTimes(2);
  });
});
