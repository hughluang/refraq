import { expect, it, vi } from "vitest";

import { getDataRow, queryDataRows } from "./accessApi";

it("looks up and opens an exact 64-bit key using JSON integer tokens", async () => {
  const id = BigInt("9223372036854775807");
  const row = '{"row_id":9223372036854775807,"meta":{"external_id":9007199254740993}}';
  const fetch = vi.fn()
    .mockResolvedValueOnce(new Response('{"items":[' + row + '],"total":1,"offset":0,"limit":50}'))
    .mockResolvedValueOnce(new Response('{"row":' + row + '}'));
  vi.stubGlobal("fetch", fetch);
  try {
    const { items } = await queryDataRows("orders", { filters: { field: "row_id", op: "eq", value: id } });
    expect(items[0].row_id).toBe(id);
    const result = await getDataRow("orders", { row_id: id });
    expect(result.row.meta).toEqual({ external_id: BigInt("9007199254740993") });
    expect(fetch.mock.calls[0][1].body).toContain('"value":9223372036854775807');
    expect(fetch.mock.calls[1][1].body).toBe('{"row_id":9223372036854775807}');
  } finally {
    vi.unstubAllGlobals();
  }
});
