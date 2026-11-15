import { describe, expect, it } from "vitest";
import type { CatalogJoin, CatalogObject } from "@/features/sources/types";
import { projectRelations, projectRoute, relationCurve } from "./relationGraph";

const object: CatalogObject = {
  id: "orders", locator_key: "obj/pg/demo/public/table/orders", source_id: "source", schema_name: "public", name: "orders", object_type: "table", business_name: null, business_description: null, ddl: null, collected_at: null, is_present: true,
  columns: [{ id: "id", locator_key: "col/pg/demo/public/table/orders/column/id", name: "id", data_type: "int", nullable: false, business_name: null, business_description: null, ordinal: 1, is_present: true }, { id: "old", locator_key: "col/pg/demo/public/table/orders/column/old", name: "old", data_type: "int", nullable: true, business_name: null, business_description: null, ordinal: 2, is_present: false }],
};
const join: CatalogJoin = { id: "a", from_column_id: "id", to_column_id: "remote", to_column_locator_key: "col/pg/other/public/table/lines/column/order_id", evidence: "Mapping", join_kind: "LEFT", created_at: "2026-11-01T00:00:00Z", created_by_user_id: null };

describe("projectRelations", () => {
  it("keeps exact column ports and separate parallel, reverse and same-object definitions", () => {
    const graph = projectRelations(object, [join, { ...join, id: "b", from_column_id: "old" }, { ...join, id: "reverse", from_column_id: "remote", from_column_locator_key: join.to_column_locator_key, to_column_id: "id", to_column_locator_key: null }, { ...join, id: "self", to_column_id: "old", to_column_locator_key: null }]);
    expect(graph.nodes).toHaveLength(2);
    expect(graph.edges.map((edge) => edge.id)).toEqual(["a", "b", "reverse", "self"]);
    expect(graph.edges[0]).toMatchObject({ source: object.locator_key, sourceHandle: "from:id:right", targetHandle: "to:remote:left", kind: "LEFT" });
    expect(graph.edges[2]).toMatchObject({ target: object.locator_key, sourceHandle: "from:remote:left", targetHandle: "to:id:right" });
    expect(graph.edges[3]).toMatchObject({ sourceHandle: "from:id:left", targetHandle: "to:old:left" });
    expect(graph.edges[3].source).toBe(graph.edges[3].target);
    expect(new Set(graph.edges.map((edge) => edge.lane)).size).toBeGreaterThan(1);
    expect(graph.nodes[0].columns.find((column) => column.id === "old")?.presence).toBe("absent");
  });
  it("keeps unresolved endpoints separate and rejected rows honest without remote metadata", () => {
    const graph = projectRelations(object, [{ ...join, is_rejected: true, to_column_locator_key: null }, { ...join, id: "missing", to_column_id: "other", to_column_locator_key: "invalid/locator" }]);
    expect(graph.nodes.map((node) => node.id)).toEqual([object.locator_key, "unresolved:remote", "unresolved:other"]);
    expect(graph.nodes[1]).toMatchObject({ name: "remote", identity: "remote", columns: [{ id: "remote", name: "remote", presence: "unknown" }] });
    expect(graph.nodes[2].identity).toBe("invalid/locator");
    expect(graph.edges[0].rejected).toBe(true);
    expect(graph.nodes[1].columns[0].dataType).toBeUndefined();
  });
  it("routes a same-object curve outside the left ports with its label on the curve", () => {
    expect(relationCurve(80, 200, 80, 254, 1, true)).toEqual({ path: "M 80,200 C -16,200 -16,254 80,254", x: 8, y: 227 });
  });
  it("preserves ordered multi-object hops without turning hop records into editable joins", () => {
    const route = { path_summary: "two remote objects", hops: [
      { join_id: "first", from_column_id: "id", to_column_id: "remote", to_column_locator_key: join.to_column_locator_key, join_kind: "LEFT", evidence: "First" },
      { join_id: "second", from_column_id: "remote", from_column_locator_key: join.to_column_locator_key, to_column_id: "third", to_column_locator_key: "col/pg/demo/public/table/accounts/column/id", join_kind: "RIGHT", evidence: "Second" },
    ] };
    const graph = projectRoute(object, route, []);
    expect(graph.nodes.map((node) => node.id)).toEqual([object.locator_key, "obj/pg/other/public/table/lines", "obj/pg/demo/public/table/accounts"]);
    expect(graph.edges).toMatchObject([
      { id: "hop:0", sourceHandle: "from:id:right", targetHandle: "to:remote:left", kind: "LEFT", stored: false },
      { id: "hop:1", sourceHandle: "from:remote:left", targetHandle: "to:third:left", kind: "RIGHT", stored: false },
    ]);
    expect(graph.edges[0]).not.toHaveProperty("evidence");
    expect(graph.edges[0]).not.toHaveProperty("created_by_user_id");
  });
  it("keeps known stored orientation separate from reverse traversal and never guesses unknown orientation", () => {
    const hop = { join_id: "a", from_column_id: "remote", to_column_id: "id", from_column_locator_key: join.to_column_locator_key, join_kind: "LEFT", join_expression: "original expression", evidence: "reported evidence" };
    const known = projectRoute(object, { path_summary: "reverse", hops: [hop] }, [join]);
    expect(known.edges[0]).toMatchObject({ sourceHandle: "from:id:right", targetHandle: "to:remote:left", kind: "LEFT", stored: true });
    const unknown = projectRoute(object, { path_summary: "reverse", hops: [hop] }, []);
    expect(unknown.edges[0]).toMatchObject({ sourceHandle: "from:remote:left", targetHandle: "to:id:right", kind: "LEFT", stored: false });
  });
});
