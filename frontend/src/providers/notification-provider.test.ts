/** @vitest-environment jsdom */

import { createElement } from "react";
import { render } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import en from "@/locales/en-US/common.json";
import zh from "@/locales/zh-CN/common.json";

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

  it("uses the console icon and tone for each notice type", async () => {
    const { presentConsoleNotification } = await import("@/providers/notification-provider");
    const { AlertIcon, CheckIcon, ErrorIcon, InfoIcon } = await import("@/components/icons");
    presentConsoleNotification({ type: "success", title: "Saved" });
    presentConsoleNotification({ type: "info", title: "Noted" });
    presentConsoleNotification({ type: "warning", title: "Careful" });
    presentConsoleNotification({ type: "error", title: "Failed" });
    const [success, info, warning, error] = api.show.mock.calls.map(
      (call) => call[0] as { color: string; icon: { type: unknown } },
    );
    expect(success.color).toBe("green");
    expect(success.icon.type).toBe(CheckIcon);
    expect(info.color).toBe("blue");
    expect(info.icon.type).toBe(InfoIcon);
    expect(warning.color).toBe("yellow");
    expect(warning.icon.type).toBe(AlertIcon);
    expect(error.color).toBe("red");
    expect(error.icon.type).toBe(ErrorIcon);
  });

  it("closes success and info on their own and keeps warning and error until dismissed", async () => {
    const { presentConsoleNotification } = await import("@/providers/notification-provider");
    presentConsoleNotification({ type: "info", title: "Noted" });
    presentConsoleNotification({ type: "warning", title: "Careful" });
    presentConsoleNotification({ type: "error", title: "Failed", message: "detail" });
    presentConsoleNotification({ type: "success", title: "Saved", autoClose: 8000 });
    const [info, warning, error, undoable] = api.show.mock.calls.map(
      (call) => call[0] as { autoClose: number | false; message?: unknown; title?: unknown },
    );
    expect(info.autoClose).toBe(4000);
    expect(warning.autoClose).toBe(false);
    expect(error.autoClose).toBe(false);
    expect(error.title).toBe("Failed");
    expect(error.message).toBe("detail");
    expect(undoable.autoClose).toBe(8000);
  });

  it("hides a visible success so a fourth notice shows at once", async () => {
    const { presentConsoleNotification } = await import("@/providers/notification-provider");
    const success = presentConsoleNotification({ type: "success", title: "Saved" });
    presentConsoleNotification({ type: "error", title: "First" });
    presentConsoleNotification({ type: "error", title: "Second" });
    presentConsoleNotification({ type: "error", title: "Third" });
    expect(api.show).toHaveBeenCalledTimes(4);
    expect(api.hide).toHaveBeenCalledTimes(1);
    expect(api.hide).toHaveBeenCalledWith(success);
    expect(api.hide.mock.invocationCallOrder[0]).toBeLessThan(api.show.mock.invocationCallOrder[3]);
  });

  it("hides a visible info notice before a warning when a fourth notice arrives", async () => {
    const { presentConsoleNotification } = await import("@/providers/notification-provider");
    const info = presentConsoleNotification({ type: "info", title: "Noted" });
    presentConsoleNotification({ type: "warning", title: "First" });
    presentConsoleNotification({ type: "warning", title: "Second" });
    presentConsoleNotification({ type: "warning", title: "Third" });
    expect(api.show).toHaveBeenCalledTimes(4);
    expect(api.hide).toHaveBeenCalledTimes(1);
    expect(api.hide).toHaveBeenCalledWith(info);
  });

  it("hides the oldest error when only errors are visible", async () => {
    const { presentConsoleNotification } = await import("@/providers/notification-provider");
    const oldest = presentConsoleNotification({ type: "error", title: "First" });
    const middle = presentConsoleNotification({ type: "error", title: "Second" });
    presentConsoleNotification({ type: "error", title: "Third" });
    presentConsoleNotification({ type: "error", title: "Fourth" });
    expect(api.show).toHaveBeenCalledTimes(4);
    expect(api.hide).toHaveBeenCalledTimes(1);
    expect(api.hide).toHaveBeenCalledWith(oldest);
    expect(api.hide).not.toHaveBeenCalledWith(middle);
  });

  it("hides the oldest warning when only warnings are visible", async () => {
    const { presentConsoleNotification } = await import("@/providers/notification-provider");
    const oldest = presentConsoleNotification({ type: "warning", title: "First" });
    presentConsoleNotification({ type: "warning", title: "Second" });
    presentConsoleNotification({ type: "warning", title: "Third" });
    presentConsoleNotification({ type: "warning", title: "Fourth" });
    expect(api.show).toHaveBeenCalledTimes(4);
    expect(api.hide).toHaveBeenCalledTimes(1);
    expect(api.hide).toHaveBeenCalledWith(oldest);
  });

  it("hides the oldest success even when an error is older", async () => {
    const { presentConsoleNotification } = await import("@/providers/notification-provider");
    const olderError = presentConsoleNotification({ type: "error", title: "First" });
    const success = presentConsoleNotification({ type: "success", title: "Saved" });
    presentConsoleNotification({ type: "error", title: "Second" });
    presentConsoleNotification({ type: "error", title: "Third" });
    expect(api.hide).toHaveBeenCalledTimes(1);
    expect(api.hide).toHaveBeenCalledWith(success);
    expect(api.hide).not.toHaveBeenCalledWith(olderError);
  });

  it("hides the older info notice before a newer success", async () => {
    const { presentConsoleNotification } = await import("@/providers/notification-provider");
    const info = presentConsoleNotification({ type: "info", title: "Noted" });
    const success = presentConsoleNotification({ type: "success", title: "Saved" });
    presentConsoleNotification({ type: "error", title: "Failed" });
    presentConsoleNotification({ type: "error", title: "Again" });
    expect(api.hide).toHaveBeenCalledTimes(1);
    expect(api.hide).toHaveBeenCalledWith(info);
    expect(api.hide).not.toHaveBeenCalledWith(success);
  });

  it("frees a slot when a notice closes itself", async () => {
    const { presentConsoleNotification } = await import("@/providers/notification-provider");
    presentConsoleNotification({ type: "success", title: "Saved" });
    presentConsoleNotification({ type: "error", title: "First" });
    presentConsoleNotification({ type: "error", title: "Second" });
    const success = api.show.mock.calls[0][0] as { onClose: () => void };
    success.onClose();
    api.hide.mockClear();
    presentConsoleNotification({ type: "error", title: "Third" });
    expect(api.hide).not.toHaveBeenCalled();
    expect(api.show).toHaveBeenCalledTimes(4);
  });

  it("updates a visible notice when the same type and original title happen again", async () => {
    const runtime = await import("@/providers/i18n-runtime");
    const { presentConsoleNotification } = await import("@/providers/notification-provider");
    runtime.bindClientI18n({
      t: (key: string) => (key === "feedback.repeated" ? "Repeated {{count}} times" : key),
    } as never);
    presentConsoleNotification({ type: "error", title: "One" });
    presentConsoleNotification({ type: "error", title: "Two" });
    const failed = presentConsoleNotification({
      type: "error",
      title: "Failed",
      message: "one",
    });
    const again = presentConsoleNotification({
      id: "other",
      type: "error",
      title: "Failed",
      message: "two",
    });
    expect(again).toBe(failed);
    expect(api.show).toHaveBeenCalledTimes(3);
    expect(api.update).toHaveBeenCalledTimes(1);
    expect(api.hide).not.toHaveBeenCalled();
    const updated = api.update.mock.calls[0][0] as { id: string; title: string; message: string };
    expect(updated.id).toBe(failed);
    expect(updated.title).toBe("Failed Repeated 2 times");
    expect(updated.message).toBe("two");

    presentConsoleNotification({ type: "error", title: "Failed" });
    expect(api.show).toHaveBeenCalledTimes(3);
    const counted = api.update.mock.calls[1][0] as { title: string };
    expect(counted.title).toBe("Failed Repeated 3 times");

    presentConsoleNotification({ type: "error", title: "Failed Repeated 2 times" });
    expect(api.show).toHaveBeenCalledTimes(4);
    expect(api.hide).toHaveBeenCalledTimes(1);
    expect(api.hide).toHaveBeenCalledWith(
      (api.show.mock.calls[0][0] as { id: string }).id,
    );
  });

  it("maps Refine success, info, warning, error, and progress onto console types", async () => {
    const { notificationProvider } = await import("@/providers/notification-provider");
    const { AlertIcon, CheckIcon, ErrorIcon, InfoIcon } = await import("@/components/icons");
    for (const type of ["success", "info", "warning", "error", "progress"]) {
      notificationProvider.open({
        key: type,
        message: type,
        type: type as "success",
      });
    }
    const shown = api.show.mock.calls.map(
      (call) => call[0] as { color: string; icon: { type: unknown }; autoClose: number | false },
    );
    expect(shown[0]).toMatchObject({ color: "green", autoClose: 4000 });
    expect(shown[0].icon.type).toBe(CheckIcon);
    expect(shown[1]).toMatchObject({ color: "blue", autoClose: 4000 });
    expect(shown[1].icon.type).toBe(InfoIcon);
    expect(shown[2]).toMatchObject({ color: "yellow", autoClose: false });
    expect(shown[2].icon.type).toBe(AlertIcon);
    expect(shown[3]).toMatchObject({ color: "red", autoClose: false });
    expect(shown[3].icon.type).toBe(ErrorIcon);
    expect(shown[4]).toMatchObject({ color: "blue", autoClose: 4000 });
    expect(shown[4].icon.type).toBe(InfoIcon);
  });

  it("replaces a Refine notice with the same id and ignores undoable timeout", async () => {
    const { notificationProvider } = await import("@/providers/notification-provider");
    notificationProvider.open({ key: "job", message: "Working", type: "progress" });
    notificationProvider.open({
      key: "job",
      message: "Finished",
      type: "success",
      undoableTimeout: 8000,
      cancelMutation: () => undefined,
    });
    expect(api.show).toHaveBeenCalledTimes(1);
    expect(api.update).toHaveBeenCalledTimes(1);
    const updated = api.update.mock.calls[0][0] as {
      id: string;
      title: string;
      autoClose: number | false;
      color: string;
      cancelMutation?: unknown;
    };
    expect(updated.id).toBe("job");
    expect(updated.title).toBe("Finished");
    expect(updated.color).toBe("green");
    expect(updated.autoClose).toBe(4000);
    expect(updated.cancelMutation).toBeUndefined();
    notificationProvider.close("job");
    expect(api.hide).toHaveBeenCalledWith("job");
  });

  it("does not merge a different type that reuses a title", async () => {
    const { presentConsoleNotification } = await import("@/providers/notification-provider");
    presentConsoleNotification({ type: "success", title: "Saved" });
    presentConsoleNotification({ type: "error", title: "Saved" });
    expect(api.show).toHaveBeenCalledTimes(2);
    expect(api.update).not.toHaveBeenCalled();
  });

  it("starts again after a repeated notice is dismissed", async () => {
    const runtime = await import("@/providers/i18n-runtime");
    const { dismissConsoleNotification, presentConsoleNotification } = await import(
      "@/providers/notification-provider"
    );
    runtime.bindClientI18n({
      t: (key: string) => (key === "feedback.repeated" ? "Repeated {{count}} times" : key),
    } as never);
    const id = presentConsoleNotification({ type: "error", title: "Failed" });
    presentConsoleNotification({ type: "error", title: "Failed" });
    dismissConsoleNotification(id);
    presentConsoleNotification({ type: "error", title: "Failed" });
    expect(api.show).toHaveBeenCalledTimes(2);
    expect(api.hide).toHaveBeenCalledWith(id);
    const reopened = api.show.mock.calls[1][0] as { title: string };
    expect(reopened.title).toBe("Failed");
  });

  it("stores the repeat phrase in both locales", () => {
    const english = en as Record<string, string>;
    const chinese = zh as Record<string, string>;
    expect(english["feedback.repeated"]).toBe("Repeated {{count}} times");
    expect(chinese["feedback.repeated"]).toBe("\u5df2\u91cd\u590d {{count}} \u6b21");
  });
});
