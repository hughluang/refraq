import { afterEach, expect, it, vi } from "vitest";
import { getCatalogObject, listSemanticsChanges, resolveCatalogObject } from "./catalog";

const locator = "obj/postgresql/demo/public/table/orders";
const response = (body: unknown, status = 200) => new Response(JSON.stringify(body), { status });
afterEach(() => vi.unstubAllGlobals());

it("resolves exact locators in a single direct request without ranked search", async () => {
  const fetch = vi.fn().mockResolvedValueOnce(response({ object: { id: "object-17", columns: [] } }));
  vi.stubGlobal("fetch", fetch);
  expect(await resolveCatalogObject(locator)).toEqual({ object: { id: "object-17", columns: [] } });
  expect(fetch.mock.calls.map(([url]) => url)).toEqual([
    `/api/catalog/objects/resolve?ref=${encodeURIComponent(locator)}`,
  ]);
});

it("maps 404 responses on locators and object ids to null and rejects malformed locators locally", async () => {
  const fetch = vi.fn()
    .mockResolvedValueOnce(response({ code: "CATALOG_OBJECT_NOT_FOUND", detail: "Not found" }, 404))
    .mockResolvedValueOnce(response({ code: "CATALOG_OBJECT_NOT_FOUND", detail: "Not found" }, 404));
  vi.stubGlobal("fetch", fetch);
  expect(await resolveCatalogObject(locator)).toEqual({ object: null });
  expect(fetch).toHaveBeenCalledTimes(1);
  expect(await resolveCatalogObject("obj/not/a/valid/locator")).toEqual({ object: null });
  expect(fetch).toHaveBeenCalledTimes(1);
  expect(await resolveCatalogObject("obj_missing")).toEqual({ object: null });
  expect(fetch).toHaveBeenCalledTimes(2);
});

it("keeps id detail reads non-nullable and forwards cancellation", async () => {
  const fetch = vi.fn().mockResolvedValue(response({ object: { id: "id" } }));
  vi.stubGlobal("fetch", fetch);
  const signal = new AbortController().signal;
  expect(await getCatalogObject("id", signal)).toEqual({ object: { id: "id" } });
  expect(fetch.mock.calls[0][1].signal).toBe(signal);
});

it("preserves escaped natural segments when encoding exact locator queries", async () => {
  const escaped = "obj/postgresql/demo/public/table/orders%2Farchive";
  const fetch = vi.fn().mockResolvedValueOnce(response({ object: { id: "object-17" } }));
  vi.stubGlobal("fetch", fetch);
  await resolveCatalogObject(escaped);
  expect(fetch.mock.calls[0][0]).toBe(
    `/api/catalog/objects/resolve?ref=${encodeURIComponent(escaped)}`,
  );
});

it("preserves access refusals rather than presenting them as missing objects", async () => {
  vi.stubGlobal("fetch", vi.fn().mockResolvedValue(response({ code: "AUTH_FORBIDDEN", detail: "Forbidden" }, 403)));
  await expect(resolveCatalogObject(locator)).rejects.toMatchObject({ status: 403, code: "AUTH_FORBIDDEN" });
});

it("passes filter parameters to semantics change history queries", async () => {
  const fetch = vi.fn().mockResolvedValueOnce(response({ items: [], total: 0, limit: 50, offset: 0 }));
  vi.stubGlobal("fetch", fetch);
  await listSemanticsChanges("obj_1", {
    scope: "column",
    column_id: "col_2",
    field_name: "enum_catalog",
    semantic_source: "mcp",
    limit: 50,
    offset: 0,
  });
  expect(fetch.mock.calls[0][0]).toBe(
    "/api/objects/obj_1/semantics-changes?scope=column&column_id=col_2&field_name=enum_catalog&semantic_source=mcp&limit=50&offset=0",
  );
});
