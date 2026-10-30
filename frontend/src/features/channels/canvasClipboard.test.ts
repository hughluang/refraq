import { describe, expect, it } from "vitest";

import {
  parseFragment,
  pasteFragment,
  serializeFragment,
  type ChannelFragment,
} from "@/features/channels/canvasClipboard";
import {
  EMPTY_GRAPH,
  type Graph,
  type GraphEdge,
  type GraphNode,
  type GraphNote,
  type NodeTypeSpec,
} from "@/features/channels/types";

function node(partial: Partial<GraphNode> & Pick<GraphNode, "id" | "type">): GraphNode {
  return {
    ref: partial.type.replace(/\./g, "_"),
    name: partial.type,
    position: { x: 0, y: 0 },
    config: {},
    on_error: "stop",
    retry: null,
    ...partial,
  };
}

function edge(
  id: string,
  source: string,
  target: string,
  sourcePort = "main",
  targetPort = "main",
): GraphEdge {
  return {
    id,
    source: { node_id: source, port: sourcePort },
    target: { node_id: target, port: targetPort },
  };
}

function graph(nodes: GraphNode[], edges: GraphEdge[] = [], notes?: GraphNote[]): Graph {
  return notes ? { nodes, edges, settings: EMPTY_GRAPH.settings, notes } : { nodes, edges, settings: EMPTY_GRAPH.settings };
}

function note(partial: Partial<GraphNote> & Pick<GraphNote, "id">): GraphNote {
  return {
    position: { x: 0, y: 0 },
    size: { width: 240, height: 120 },
    text: "",
    ...partial,
  };
}

function spec(type: string, extra: Partial<NodeTypeSpec> = {}): NodeTypeSpec {
  return {
    type,
    family: "action",
    label: type,
    summary: "",
    description: "",
    trigger: false,
    container: null,
    inputs: [{ port: "main", description: "" }],
    outputs: [{ port: "main", description: "" }],
    config_schema: {},
    permission: null,
    ...extra,
  };
}

const manual = spec("manual", { trigger: true, family: "trigger", outputs: [{ port: "out", description: "" }] });
const read = spec("read.sql");
const code = spec("transform.code", { permission: "channel:code_write" });

describe("canvasClipboard", () => {
  it("serializes the selection as a fragment and parses that envelope back", () => {
    const start = node({
      id: "nd_a",
      type: "manual",
      ref: "manual",
      name: "Start",
      position: { x: 8, y: 16 },
      config: { label: "keep" },
    });
    const load = node({
      id: "nd_b",
      type: "read.sql",
      ref: "read_sql",
      name: "Load",
      position: { x: 40, y: 16 },
      config: { sql: "select 1" },
    });
    const outside = node({ id: "nd_c", type: "read.sql", ref: "read_sql_2", name: "Other" });
    const linked = edge("ed_ab", "nd_a", "nd_b", "out", "main");
    const leaves = edge("ed_ac", "nd_a", "nd_c", "out", "main");
    const current = graph([start, load, outside], [linked, leaves]);

    const fragment = serializeFragment(current, ["nd_a", "nd_b"]);

    expect(fragment).toEqual({
      kind: "refraq.channel.fragment",
      version: 1,
      nodes: [start, load],
      edges: [linked],
      notes: [],
    });
    start.config.label = "changed";
    expect(fragment.nodes[0]?.config).toEqual({ label: "keep" });
    expect(parseFragment(JSON.stringify(fragment))).toEqual(fragment);
  });

  it("parses a fragment that already carries notes and rejects a bad envelope", () => {
    const kept = node({ id: "nd_a", type: "read.sql", name: "Load" });
    const text = JSON.stringify({
      kind: "refraq.channel.fragment",
      version: 1,
      nodes: [kept],
      edges: [],
      notes: [note({ id: "nt_1", text: "later", position: { x: 4, y: 8 }, size: { width: 200, height: 90 } })],
    });

    expect(parseFragment(text)?.notes).toEqual([
      note({ id: "nt_1", text: "later", position: { x: 4, y: 8 }, size: { width: 200, height: 90 } }),
    ]);
    expect(parseFragment("not json")).toBeNull();
    expect(parseFragment("[]")).toBeNull();
    expect(
      parseFragment(
        JSON.stringify({ kind: "other", version: 1, nodes: [], edges: [], notes: [] }),
      ),
    ).toBeNull();
    expect(
      parseFragment(
        JSON.stringify({
          kind: "refraq.channel.fragment",
          version: 2,
          nodes: [],
          edges: [],
          notes: [],
        }),
      ),
    ).toBeNull();
    expect(
      parseFragment(
        JSON.stringify({
          kind: "refraq.channel.fragment",
          version: 1,
          nodes: [{ id: "nd_a" }],
          edges: [],
          notes: [],
        }),
      ),
    ).toBeNull();
    expect(
      parseFragment(
        JSON.stringify({ kind: "refraq.channel.fragment", version: 1, nodes: [], edges: [] }),
      ),
    ).toBeNull();
    expect(
      parseFragment(
        JSON.stringify({
          kind: "refraq.channel.fragment",
          version: 1,
          nodes: [],
          edges: [{ id: "ed_a" }],
          notes: [],
        }),
      ),
    ).toBeNull();
    expect(
      parseFragment(
        JSON.stringify({
          kind: "refraq.channel.fragment",
          version: 1,
          nodes: [],
          edges: [],
          notes: [{ id: "nt_1", text: "later" }],
        }),
      ),
    ).toBeNull();
  });

  it("serializes selected notes and pastes them with new ids, off the node list", () => {
    const kept = note({
      id: "nt_keep",
      position: { x: 10, y: 20 },
      size: { width: 240, height: 120 },
      text: "keep\nme",
    });
    const source = node({
      id: "nd_a",
      type: "read.sql",
      name: "Load",
      position: { x: 0, y: 0 },
    });
    const current = graph(
      [source, node({ id: "nd_b", type: "read.sql", name: "Other" })],
      [],
      [kept, note({ id: "nt_out", text: "out" })],
    );

    const fragment = serializeFragment(current, ["nd_a", "nt_keep"]);

    expect(fragment.notes).toEqual([kept]);
    expect(fragment.nodes.map((item) => item.id)).toEqual(["nd_a"]);
    kept.text = "changed";
    expect(fragment.notes[0]?.text).toBe("keep\nme");

    const pasted = pasteFragment(fragment, graph([]), [read], [], null);

    expect(pasted.nodes).toHaveLength(1);
    expect(pasted.nodes[0]?.id.startsWith("nd_")).toBe(true);
    expect(pasted.nodes[0]?.position).toEqual({ x: 40, y: 40 });
    expect(pasted.notes).toHaveLength(1);
    expect(pasted.notes[0]?.id).toMatch(/^nt_[0-9a-f]{12}$/);
    expect(pasted.notes[0]?.id).not.toBe("nt_keep");
    expect(pasted.notes[0]?.text).toBe("keep\nme");
    expect(pasted.notes[0]?.size).toEqual({ width: 240, height: 120 });
    expect(pasted.notes[0]?.position).toEqual({ x: 50, y: 60 });
    expect(pasted.nodes.some((item) => item.id === pasted.notes[0]?.id)).toBe(false);
  });

  it("anchors pasted notes with the nodes, and still pastes notes when every node is skipped", () => {
    const fragment: ChannelFragment = {
      kind: "refraq.channel.fragment",
      version: 1,
      nodes: [node({ id: "nd_a", type: "read.sql", position: { x: 100, y: 80 } })],
      edges: [],
      notes: [
        note({
          id: "nt_a",
          position: { x: 140, y: 200 },
          text: "beside",
        }),
      ],
    };

    const anchored = pasteFragment(fragment, graph([]), [read], [], { x: 10, y: 30 });

    expect(anchored.nodes[0]?.position).toEqual({ x: 10, y: 30 });
    expect(anchored.notes[0]?.position).toEqual({ x: 50, y: 150 });

    const skipped = pasteFragment(
      {
        ...fragment,
        nodes: [node({ id: "nd_x", type: "missing.type", position: { x: 0, y: 0 } })],
      },
      graph([]),
      [read],
      [],
      null,
    );
    expect(skipped.nodes).toEqual([]);
    expect(skipped.skipped.unknown).toBe(1);
    expect(skipped.notes).toHaveLength(1);
    expect(skipped.notes[0]?.position).toEqual({ x: 180, y: 240 });
    expect(skipped.notes[0]?.text).toBe("beside");
  });

  it("pastes into another graph with new ids, a suffixed name, a new ref, and a deep-copied config", () => {
    const config = { sql: "select 1", nested: { template: "{{ nodes.manual.rows }}" } };
    const source = node({
      id: "nd_src",
      type: "read.sql",
      ref: "read_sql",
      name: "Load",
      position: { x: 12, y: 20 },
      config,
      on_error: "continue",
      retry: { max_tries: 2, wait_sec: 5 },
      type_version: 3,
    });
    const fragment = serializeFragment(graph([source], []), ["nd_src"]);
    const resident = node({
      id: "nd_here",
      type: "read.sql",
      ref: "read_sql",
      name: "Load",
      position: { x: 1, y: 1 },
    });

    const pasted = pasteFragment(fragment, graph([resident]), [read], [], null);

    expect(pasted.nodes).toHaveLength(1);
    expect(pasted.edges).toEqual([]);
    expect(pasted.skipped).toEqual({ trigger: 0, permission: 0, unknown: 0, permissions: [] });
    const created = pasted.nodes[0];
    expect(created?.id).toMatch(/^nd_/);
    expect(created?.id).not.toBe("nd_src");
    expect(created?.id).not.toBe("nd_here");
    expect(created?.name).toBe("Load 2");
    expect(created?.ref).toBe("read_sql_2");
    expect(created?.type).toBe("read.sql");
    expect(created?.on_error).toBe("continue");
    expect(created?.retry).toEqual({ max_tries: 2, wait_sec: 5 });
    expect(created?.type_version).toBe(3);
    expect(created?.position).toEqual({ x: 52, y: 60 });
    expect(created?.config).toEqual({
      sql: "select 1",
      nested: { template: "{{ nodes.manual.rows }}" },
    });
    expect(created?.config).not.toBe(config);
    expect(created?.config.nested).not.toBe(config.nested);
    expect(resident.position).toEqual({ x: 1, y: 1 });
  });

  it("bases the new ref on the fragment ref, including an empty one", () => {
    const incoming = node({ id: "nd_src", type: "read.sql", ref: "", name: "Load" });
    const fragment = serializeFragment(graph([incoming]), ["nd_src"]);

    const pasted = pasteFragment(fragment, graph([]), [read], [], null);

    expect(fragment.nodes[0]?.ref).toBe("");
    expect(pasted.nodes[0]?.ref).toBe("node");
  });

  it("numbers later copies when the suffixed name is already taken", () => {
    const incoming = node({ id: "nd_src", type: "read.sql", ref: "fresh", name: "Load" });
    const fragment = serializeFragment(graph([incoming]), ["nd_src"]);
    const current = graph([
      node({ id: "nd_1", type: "read.sql", ref: "read_sql", name: "Load" }),
      node({ id: "nd_2", type: "read.sql", ref: "read_sql_2", name: "Load 2" }),
    ]);

    const pasted = pasteFragment(fragment, current, [read], [], null);

    expect(pasted.nodes.map((item) => item.name)).toEqual(["Load 3"]);
    expect(pasted.nodes[0]?.ref).toBe("fresh");
  });

  it("places the fragment's top-left on the anchor", () => {
    const first = node({
      id: "nd_a",
      type: "read.sql",
      ref: "read_sql",
      name: "A",
      position: { x: 10, y: 30 },
    });
    const second = node({
      id: "nd_b",
      type: "read.sql",
      ref: "read_sql_2",
      name: "B",
      position: { x: 40, y: 50 },
    });
    const fragment = serializeFragment(graph([first, second], [edge("ed_ab", "nd_a", "nd_b")]), [
      "nd_a",
      "nd_b",
    ]);

    const pasted = pasteFragment(fragment, graph([]), [read], [], { x: 100, y: 200 });

    expect(pasted.nodes.map((item) => item.position)).toEqual([
      { x: 100, y: 200 },
      { x: 130, y: 220 },
    ]);
    expect(pasted.edges).toHaveLength(1);
    expect(pasted.edges[0]?.id).toMatch(/^ed_/);
    expect(pasted.edges[0]?.id).not.toBe("ed_ab");
    expect(pasted.edges[0]?.source).toEqual({ node_id: pasted.nodes[0]?.id, port: "main" });
    expect(pasted.edges[0]?.target).toEqual({ node_id: pasted.nodes[1]?.id, port: "main" });
  });

  it("skips a second trigger, a forbidden type, and an unknown type, and drops edges that cite them", () => {
    const trigger = node({
      id: "nd_t",
      type: "manual",
      ref: "manual",
      name: "Start",
      position: { x: 0, y: 0 },
    });
    const again = node({
      id: "nd_t2",
      type: "manual",
      ref: "manual_2",
      name: "Start again",
      position: { x: 80, y: 0 },
    });
    const denied = node({
      id: "nd_code",
      type: "transform.code",
      ref: "transform_code",
      name: "Code",
      position: { x: 0, y: 80 },
    });
    const missing = node({
      id: "nd_gone",
      type: "missing.type",
      ref: "missing_type",
      name: "Gone",
    });
    const kept = node({
      id: "nd_load",
      type: "read.sql",
      ref: "read_sql",
      name: "Load",
      position: { x: 16, y: 24 },
    });
    const fragment: ChannelFragment = {
      kind: "refraq.channel.fragment",
      version: 1,
      nodes: [trigger, again, denied, missing, kept],
      edges: [
        edge("ed_trigger", "nd_t", "nd_load", "out"),
        edge("ed_code", "nd_code", "nd_load"),
        edge("ed_gone", "nd_gone", "nd_load"),
      ],
      notes: [],
    };
    const resident = node({
      id: "nd_has",
      type: "manual",
      ref: "manual_9",
      name: "Already",
      position: { x: 4, y: 4 },
    });

    const blocked = pasteFragment(fragment, graph([resident]), [manual, read, code], [], {
      x: 70,
      y: 90,
    });

    expect(blocked.nodes.map((item) => item.type)).toEqual(["read.sql"]);
    expect(blocked.nodes[0]?.position).toEqual({ x: 70, y: 90 });
    expect(blocked.nodes[0]?.name).toBe("Load");
    expect(blocked.edges).toEqual([]);
    expect(blocked.skipped).toEqual({
      trigger: 2,
      permission: 1,
      unknown: 1,
      permissions: ["channel:code_write"],
    });
    expect(resident.position).toEqual({ x: 4, y: 4 });

    const open = pasteFragment(fragment, graph([]), [manual, read, code], ["channel:code_write"], null);
    expect(open.nodes.map((item) => item.type)).toEqual(["manual", "transform.code", "read.sql"]);
    expect(open.skipped).toEqual({
      trigger: 1,
      permission: 0,
      unknown: 1,
      permissions: [],
    });
    const idOf = (name: string) => open.nodes.find((item) => item.name === name)?.id;
    expect(open.edges.map((item) => [item.source.node_id, item.target.node_id])).toEqual([
      [idOf("Start"), idOf("Load")],
      [idOf("Code"), idOf("Load")],
    ]);
  });

  it("returns no nodes when every selected node is skipped", () => {
    const trigger = node({ id: "nd_t", type: "manual", name: "Start" });
    const fragment = serializeFragment(graph([trigger]), ["nd_t"]);
    const resident = node({ id: "nd_has", type: "manual", ref: "manual", name: "Start" });

    const pasted = pasteFragment(fragment, graph([resident]), [manual], [], null);

    expect(pasted.nodes).toEqual([]);
    expect(pasted.edges).toEqual([]);
    expect(pasted.skipped.trigger).toBe(1);
    expect(resident.position).toEqual({ x: 0, y: 0 });
  });
});
