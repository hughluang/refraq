import { describe, expect, it } from "vitest";

import {
  EDITOR_ROW_LIMIT,
  clampRowLimit,
  dryRunSummary,
  editorPhaseByNode,
  latestEditorExecution,
  loadPins,
  pinsForGraph,
  savePins,
  withPin,
  withoutPin,
} from "@/features/channels/editorSession";
import en from "@/locales/en-US/common.json";
import zh from "@/locales/zh-CN/common.json";

function memoryStorage(): Storage {
  const data = new Map<string, string>();
  return {
    get length() {
      return data.size;
    },
    clear: () => data.clear(),
    getItem: (key) => data.get(key) ?? null,
    key: (index) => [...data.keys()][index] ?? null,
    removeItem: (key) => {
      data.delete(key);
    },
    setItem: (key, value) => {
      data.set(key, value);
    },
  };
}

describe("editor execution helpers", () => {
  it("clamps the row limit to the contract range", () => {
    expect(clampRowLimit("")).toBe(EDITOR_ROW_LIMIT);
    expect(clampRowLimit(null)).toBe(EDITOR_ROW_LIMIT);
    expect(clampRowLimit(1.5)).toBe(EDITOR_ROW_LIMIT);
    expect(clampRowLimit(0)).toBe(1);
    expect(clampRowLimit(5000)).toBe(1000);
    expect(clampRowLimit("25")).toBe(25);
  });

  it("derives succeeded, failed, pinned, and not-reached colours", () => {
    const phases = editorPhaseByNode(
      ["start", "read", "write", "later"],
      [
        { seq: 1, node_id: "start", status: "succeeded" },
        { seq: 2, node_id: "read", status: "skipped" },
        { seq: 3, node_id: "write", status: "pinned" },
        { seq: 4, node_id: "write", status: "failed" },
        { seq: 5, node_id: "later", status: "cancelled" },
      ],
    );
    expect(phases.get("start")).toBe("succeeded");
    expect(phases.get("read")).toBe("succeeded");
    expect(phases.get("write")).toBe("failed");
    expect(phases.get("later")).toBe("failed");
    expect(phases.get("missing")).toBeUndefined();

    const pinned = editorPhaseByNode(
      ["kept", "gone"],
      [{ seq: 1, node_id: "kept", status: "pinned" }],
    );
    expect(pinned.get("kept")).toBe("pinned");
    expect(pinned.get("gone")).toBe("dead");
  });

  it("keeps the latest execution for a node", () => {
    const latest = latestEditorExecution(
      [
        { seq: 1, node_id: "body", output: { n: 1 } },
        { seq: 4, node_id: "other", output: { n: 9 } },
        { seq: 3, node_id: "body", output: { n: 3 } },
      ],
      "body",
    );
    expect(latest?.output).toEqual({ n: 3 });
    expect(latestEditorExecution([], "body")).toBeNull();
  });

  it("summarises dry-run counts and ignores real reads", () => {
    expect(
      dryRunSummary("write.entity", {
        inserted: 2,
        updated: 1,
        unchanged: 4,
        deleted: 0,
        unmatched: 3,
        dry_run: true,
      }),
    ).toEqual({
      kind: "write.entity",
      inserted: 2,
      updated: 1,
      unchanged: 4,
      deleted: 0,
      unmatched: 3,
    });
    expect(dryRunSummary("write.entity", { inserted: 1, dry_run: true })).toBeNull();
    expect(dryRunSummary("state.variable", { applied: false, dry_run: true })).toEqual({
      kind: "state.variable",
      applied: false,
    });
    expect(dryRunSummary("state.variable", { value: 1 })).toBeNull();
    expect(dryRunSummary("read.sql", { rows: [], dry_run: true })).toBeNull();
  });

  it("stores pins per channel and drops nodes that are gone or For", () => {
    const storage = memoryStorage();
    savePins(storage, "chn_1", [
      { node_id: "read", output: { rows: [1] } },
      { node_id: "walk", output: { current: 0 } },
    ]);
    expect(loadPins(storage, "chn_1")).toEqual([
      { node_id: "read", output: { rows: [1] } },
      { node_id: "walk", output: { current: 0 } },
    ]);
    expect(loadPins(storage, "chn_2")).toEqual([]);
    storage.setItem("refraq.channel.editor-pins.chn_3", "{");
    expect(loadPins(storage, "chn_3")).toEqual([]);

    const pruned = pinsForGraph(loadPins(storage, "chn_1"), [
      { id: "read", type: "read.sql" },
      { id: "walk", type: "volume.for" },
    ]);
    expect(pruned).toEqual([{ node_id: "read", output: { rows: [1] } }]);

    const replaced = withPin(pruned, { node_id: "read", output: { rows: [2] } });
    expect(replaced).toEqual([{ node_id: "read", output: { rows: [2] } }]);
    expect(withoutPin(replaced, "read")).toEqual([]);
  });

  it("keeps editor copy distinct from Run up to this node in both languages", () => {
    const enMessages = en as Record<string, string>;
    const zhMessages = zh as Record<string, string>;
    const keys = (messages: Record<string, string>) =>
      Object.keys(messages)
        .filter((key) => key.startsWith("channels.editor."))
        .sort();
    const enKeys = keys(enMessages);
    expect(keys(zhMessages)).toEqual(enKeys);
    expect(enKeys.length).toBeGreaterThan(0);
    for (const key of enKeys) {
      expect(enMessages[key]).not.toBe("");
      expect(zhMessages[key]).not.toBe("");
    }
    expect(enMessages["channels.editor.test"]).not.toBe(enMessages["channels.node.run"]);
    expect(zhMessages["channels.editor.test"]).not.toBe(zhMessages["channels.node.run"]);
    expect(enMessages["channels.editor.hint"]).not.toBe(enMessages["channels.run.writesUpTo"]);
    expect(zhMessages["channels.editor.hint"]).not.toBe(zhMessages["channels.run.writesUpTo"]);
  });
});
