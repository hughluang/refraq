import { beforeEach, expect, it, vi } from "vitest";
import { listMirrors, requestRecovery, setMirrorEnabled } from "./api";

const api = vi.hoisted(() => vi.fn());
vi.mock("@/lib/api", () => ({ apiClient: api }));
beforeEach(() => api.mockReset());

it("sends literal global filters and offset pagination without requesting rows", async () => {
  await listMirrors({ source_id: "source/a", status: "unknown", q: "a_%", limit: 50, offset: 100 });
  expect(api).toHaveBeenCalledWith("/mirrors?source_id=source%2Fa&status=unknown&q=a_%25&limit=50&offset=100");
});

it("binds recovery to the selected mirror and observed history epoch", async () => {
  await requestRecovery("mirror/a", { action: "run_now", expected_history_epoch: 7, reason: "Approved state repair" });
  expect(api).toHaveBeenCalledWith("/mirrors/mirror%2Fa/recovery-requests", expect.objectContaining({ method: "POST", body: JSON.stringify({ action: "run_now", expected_history_epoch: 7, reason: "Approved state repair" }) }));
});

it("returns disable acceptance without claiming runtime stop", async () => {
  api.mockResolvedValue({ mirror: { status: "disable_pending", enabled: false }, operation_id: "op-1" });
  const result = await setMirrorEnabled("m1", false);
  expect(result.mirror.status).toBe("disable_pending");
  expect(api).toHaveBeenCalledWith("/mirrors/m1", expect.objectContaining({ method: "PATCH", body: '{"enabled":false}' }));
});
