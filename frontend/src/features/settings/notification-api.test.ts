import { expect, it, vi } from "vitest";
import { getNotificationChannel, replaceNotificationChannel, testNotificationChannel } from "./notification-api";
const api = vi.hoisted(() => vi.fn());
vi.mock("@/lib/api", () => ({ apiClient: api }));
it("reads only redacted configuration and replaces both routes without patch semantics", async () => {
  await getNotificationChannel();
  expect(api).toHaveBeenLastCalledWith("/settings/notification-channel");
  const config = { primary: { https_url: "https://primary.example", credential: { header_name: "Authorization", secret: "replacement-primary" } }, fallback: { https_url: "https://fallback.example", credential: { header_name: "Authorization", secret: "replacement-fallback" } }, responder: "on-call" };
  await replaceNotificationChannel(config);
  expect(api).toHaveBeenLastCalledWith("/settings/notification-channel", expect.objectContaining({ method: "PUT", body: JSON.stringify(config) }));
  api.mockResolvedValue({ operation_id: "test-1", state: "pending" });
  expect(await testNotificationChannel()).toEqual({ operation_id: "test-1", state: "pending" });
  expect(api).toHaveBeenLastCalledWith("/settings/notification-channel/test", { method: "POST" });
});
