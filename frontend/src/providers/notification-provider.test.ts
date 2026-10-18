/** @vitest-environment jsdom */

import { createElement } from "react";
import { render } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

const api = vi.hoisted(() => ({
  show: vi.fn(),
  update: vi.fn(),
  hide: vi.fn(),
  clean: vi.fn(),
  props: null as Record<string, unknown> | null,
}));

vi.mock("@mantine/notifications", () => ({
  notifications: {
    show: api.show,
    update: api.update,
    hide: api.hide,
    clean: api.clean,
  },
  Notifications: (props: Record<string, unknown>) => {
    api.props = props;
    return null;
  },
}));

describe("console notifications", () => {
  beforeEach(async () => {
    api.show.mockClear();
    api.update.mockClear();
    api.hide.mockClear();
    api.clean.mockClear();
    api.props = null;
    vi.resetModules();
  });

  it("keeps errors open and closes success after 4 seconds", async () => {
    const { presentConsoleNotification } = await import("@/providers/notification-provider");
    presentConsoleNotification({ type: "success", title: "Saved" });
    presentConsoleNotification({ type: "error", title: "Failed" });
    const success = api.show.mock.calls[0][0] as { autoClose: number | false };
    const error = api.show.mock.calls[1][0] as { autoClose: number | false };
    expect(success.autoClose).toBe(4000);
    expect(error.autoClose).toBe(false);
  });

  it("replaces an open notification that keeps the same id", async () => {
    const { presentConsoleNotification } = await import("@/providers/notification-provider");
    const id = presentConsoleNotification({ id: "job-1", type: "success", title: "Working" });
    presentConsoleNotification({ id, type: "success", title: "Finished" });
    expect(api.show).toHaveBeenCalledTimes(1);
    expect(api.update).toHaveBeenCalledTimes(1);
    const updated = api.update.mock.calls[0][0] as { id: string; autoClose: number };
    expect(updated.id).toBe("job-1");
    expect(updated.autoClose).toBe(4000);
  });

  it("shows at most three notices at the top right", async () => {
    const { ConsoleNotifications } = await import("@/providers/notification-provider");
    render(createElement(ConsoleNotifications));
    expect(api.props).toMatchObject({ position: "top-right", limit: 3 });
  });
});
