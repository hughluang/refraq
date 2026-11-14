import { afterEach, expect, it, vi } from "vitest";
import { getCatalogObject, resolveCatalogObject } from "./catalog";

const locator = "obj/postgresql/demo/public/table/orders";
const response = (body: unknown) => new Response(JSON.stringify(body));
afterEach(() => vi.unstubAllGlobals());

it("resolves exact locators through stable source browsing, never ranked search", async () => {
  const fetch = vi.fn()
    .mockResolvedValueOnce(response({ items: [{ id: "wrong", key: "demo-copy", engine: "postgresql" }], total: 101 }))
    .mockResolvedValueOnce(response({ items: [{ id: "src", key: "demo", engine: "postgresql" }], total: 101 }))
    .mockResolvedValueOnce(response({ items: [{ id: "wrong", locator_key: `${locator}_archive` }], total: 101 }))
    .mockResolvedValueOnce(response({ items: [{ id: "object-17", locator_key: locator }], total: 101 }))
    .mockResolvedValueOnce(response({ object: { id: "object-17", columns: [] } }));
  vi.stubGlobal("fetch", fetch);
  expect(await resolveCatalogObject(locator)).toEqual({ object: { id: "object-17", columns: [] } });
  expect(fetch.mock.calls.map(([url]) => url)).toEqual([
    "/api/sources?q=demo&limit=100&offset=0",
    "/api/sources?q=demo&limit=100&offset=100",
    "/api/sources/src/objects?q=orders&limit=100&offset=0&object_type=table&include_absent=true",
    "/api/sources/src/objects?q=orders&limit=100&offset=100&object_type=table&include_absent=true",
    "/api/objects/object-17",
  ]);
});

it("does not load a fuzzy object or keep scanning a growing total", async () => {
  const fetch = vi.fn()
    .mockResolvedValueOnce(response({ items: [{ id: "src", key: "demo", engine: "postgresql" }], total: 1 }))
    .mockResolvedValueOnce(response({ items: [{ id: "wrong", locator_key: `${locator}_archive` }], total: 101 }))
    .mockResolvedValueOnce(response({ items: [{ id: "wrong2", locator_key: `${locator}_old` }], total: 1000 }));
  vi.stubGlobal("fetch", fetch);
  expect(await resolveCatalogObject(locator)).toEqual({ object: null });
  expect(fetch).toHaveBeenCalledTimes(3);
});

it("stops on an empty source page and rejects malformed locators without a lookup", async () => {
  const fetch = vi.fn().mockResolvedValue(response({ items: [], total: 1000 }));
  vi.stubGlobal("fetch", fetch);
  expect(await resolveCatalogObject(locator)).toEqual({ object: null });
  expect(fetch).toHaveBeenCalledTimes(1);
  expect(await resolveCatalogObject("obj/not/a/valid/locator")).toEqual({ object: null });
  expect(fetch).toHaveBeenCalledTimes(1);
});

it("keeps id detail reads non-nullable and forwards cancellation", async () => {
  const fetch = vi.fn().mockResolvedValue(response({ object: { id: "id" } }));
  vi.stubGlobal("fetch", fetch);
  const signal = new AbortController().signal;
  expect(await getCatalogObject("id", signal)).toEqual({ object: { id: "id" } });
  expect(fetch.mock.calls[0][1].signal).toBe(signal);
});

it("decodes an escaped natural name for browse filtering without changing the exact locator", async () => {
  const escaped = "obj/postgresql/demo/public/table/orders%2Farchive";
  const fetch = vi.fn()
    .mockResolvedValueOnce(response({ items: [{ id: "src", key: "demo", engine: "postgresql" }], total: 1 }))
    .mockResolvedValueOnce(response({ items: [{ id: "object-17", locator_key: escaped }], total: 1 }))
    .mockResolvedValueOnce(response({ object: { id: "object-17" } }));
  vi.stubGlobal("fetch", fetch);
  await resolveCatalogObject(escaped);
  expect(fetch.mock.calls[1][0]).toContain("q=orders%2Farchive");
  expect(fetch.mock.calls[2][0]).toBe("/api/objects/object-17");
});

it("preserves access refusals rather than presenting them as missing objects", async () => {
  vi.stubGlobal("fetch", vi.fn().mockResolvedValue(new Response(JSON.stringify({ code: "AUTH_FORBIDDEN", detail: "Forbidden" }), { status: 403 })));
  await expect(resolveCatalogObject(locator)).rejects.toMatchObject({ status: 403, code: "AUTH_FORBIDDEN" });
});
