import type { LayoutNode, LayoutEdge, LayoutResult } from "./graphLayout";

export type LayoutWork = {
  input: { nodes: readonly LayoutNode[]; edges: readonly LayoutEdge[] };
  ordered: Map<string, number | undefined>;
};
export type LayoutFacts = {
  topology: string;
  measurements: string;
  ready: boolean;
  adoptToken: unknown;
  mutable: boolean;
};
export type LayoutState = {
  graph: string;
  measurements: string;
  auto: boolean;
  ready: boolean;
  locked: boolean;
};
export type LayoutAttemptAdapter = {
  read(): LayoutState;
  prepare(): LayoutWork;
  run(work: LayoutWork): Promise<LayoutResult>;
  apply(work: LayoutWork, result: LayoutResult, explicit: boolean, isCurrent: () => boolean): void;
  publish(state: { pending: boolean; error: boolean }): void;
};

export function createLayoutAttempts(adapter: LayoutAttemptAdapter) {
  let generation = 0;
  let revision = 0;
  let replay = false;
  let observed: LayoutFacts | undefined;
  let error = false;

  const eligible = () => {
    const state = adapter.read();
    return state.auto && state.ready && !state.locked && !replay;
  };
  const publish = (pending: boolean) => adapter.publish({ pending, error });

  const start = async (explicit: boolean) => {
    if (adapter.read().locked || (!explicit && !eligible())) return;
    const current = ++generation;
    const isCurrent = () => current === generation;
    error = false;
    publish(true);
    try {
      const work = adapter.prepare();
      const capturedRevision = revision;
      const snapshot = adapter.read();
      const result = await adapter.run(work);
      if (!isCurrent()) return;
      const state = adapter.read();
      if (capturedRevision !== revision) {
        if (eligible()) {
          queueMicrotask(() => {
            if (isCurrent() && eligible()) void start(false);
          });
        }
        return;
      }
      if (snapshot.graph !== state.graph || snapshot.measurements !== state.measurements || state.locked) return;
      if (result.status !== "laid-out") {
        error = true;
        return;
      }
      adapter.apply(work, result, explicit, isCurrent);
    } catch {
      if (isCurrent()) error = true;
    } finally {
      if (isCurrent()) publish(false);
    }
  };

  return {
    observe(facts: LayoutFacts) {
      const changed = !observed || observed.topology !== facts.topology ||
        observed.measurements !== facts.measurements || observed.ready !== facts.ready ||
        observed.adoptToken !== facts.adoptToken || observed.mutable !== facts.mutable;
      observed = { ...facts };
      if (changed && eligible()) void start(false);
    },
    request() { return start(true); },
    edited() {
      revision += 1;
      replay = false;
    },
    invalidate(reason: "geometry" | "restore" | "adopt" | "lock" | "unmount") {
      generation += 1;
      if (reason === "restore") {
        revision += 1;
        replay = true;
      }
      if (reason === "adopt") replay = false;
      if (reason === "unmount") observed = undefined;
      else publish(false);
    },
  };
}
