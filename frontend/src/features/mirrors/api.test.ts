import { beforeEach, expect, it, vi } from "vitest";
import { getFleetOverview, getFleetThroughput, listMirrorInventory, requestRecovery, setMirrorEnabled } from "./api";

const api = vi.hoisted(() => vi.fn());
vi.mock("@/lib/api", () => ({ apiClient: api }));
beforeEach(() => api.mockReset());

it("binds recovery to the selected mirror and observed history epoch", async () => {
  await requestRecovery("mirror/a", { action: "run_now", expected_history_epoch: 7, reason: "Approved state repair" });
  expect(api).toHaveBeenCalledWith("/mirrors/mirror%2Fa/recovery-requests", expect.objectContaining({ method: "POST", body: JSON.stringify({ action: "run_now", expected_history_epoch: 7, reason: "Approved state repair" }) }));
});

it("keeps the chart window out of fleet totals and applies Inventory filters before server paging", async () => {
  const controller = new AbortController();
  await getFleetOverview({ runtime_id: "runtime/a", rank: "attention" }, controller.signal);
  expect(api).toHaveBeenLastCalledWith("/mirror-fleet?runtime_id=runtime%2Fa&rank=attention", { signal: controller.signal });
  await getFleetThroughput({ runtime_id: "runtime/a", hours: 24 }, controller.signal);
  expect(api).toHaveBeenLastCalledWith("/mirror-throughput?runtime_id=runtime%2Fa&hours=24", { signal: controller.signal });
  await listMirrorInventory({ source_id: "source/a", grouped_state: "attention", published_only: true, cause: "continuity", sort: "priority", q: "PUBLIC.Order", limit: 12, offset: 24 });
  expect(api).toHaveBeenLastCalledWith("/mirrors?source_id=source%2Fa&grouped_state=attention&published_only=true&cause=continuity&sort=priority&q=PUBLIC.Order&limit=12&offset=24");
});

it.each([
  { mirror: { status: "disable_pending", enabled: false }, operation_id: "op-1" },
  { enabled: false, operation_id: "op-1" },
])("returns the authorized disable receipt", async (receipt) => {
  api.mockResolvedValue(receipt);
  const result = await setMirrorEnabled("m1", false);
  expect(result).toEqual(receipt);
  expect(api).toHaveBeenCalledWith("/mirrors/m1", expect.objectContaining({ method: "PATCH", body: '{"enabled":false}' }));
});
