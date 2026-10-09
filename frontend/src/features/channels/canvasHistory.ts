export type History<T> = {
  past: T[];
  present: T;
  future: T[];
};

export type NodeChangeLike = {
  type: string;
  dragging?: boolean;
};

export function createHistory<T>(present: T): History<T> {
  return { past: [], present, future: [] };
}

export function pushHistory<T>(history: History<T>, next: T): History<T> {
  return { past: [...history.past, history.present], present: next, future: [] };
}

export function undoHistory<T>(history: History<T>): History<T> {
  const previous = history.past[history.past.length - 1];
  if (previous === undefined) return history;
  return {
    past: history.past.slice(0, -1),
    present: previous,
    future: [history.present, ...history.future],
  };
}

export function redoHistory<T>(history: History<T>): History<T> {
  const next = history.future[0];
  if (next === undefined) return history;
  return {
    past: [...history.past, history.present],
    present: next,
    future: history.future.slice(1),
  };
}

export function shouldCommitNodeChanges(changes: readonly NodeChangeLike[]): boolean {
  const meaningful = changes.filter((change) => change.type !== "select" && change.type !== "dimensions");
  if (meaningful.length === 0) return false;
  const liveDrag = meaningful.every((change) => change.type === "position" && change.dragging === true);
  return !liveDrag;
}

export function shouldCommitEdgeChanges(changes: readonly { type: string }[]): boolean {
  return changes.some((change) => change.type !== "select");
}
