/** @vitest-environment jsdom */

import { MantineProvider } from "@mantine/core";
import { notifications, notificationsStore } from "@mantine/notifications";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { createElement } from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { presentProblemNotification } from "@/components/feedback/presentProblemNotification";
import { ApiError } from "@/lib/api";
import { ConsoleNotifications } from "@/providers/notification-provider";

const copy = vi.hoisted(() => ({
  text: vi.fn(async (_value: string) => {}),
}));

vi.mock("@/lib/copy-text", () => ({
  copyText: (value: string) => copy.text(value),
}));

const dictionary: Record<string, string> = {
  "problems.unknown": "Something went wrong. Try again.",
  "problems.USER_GROUP_KEY_DUPLICATE": "That user group key is taken.",
  "problems.TAG_IN_USE":
    "This Tag is still assigned: Entities {{entity_count}}, Channels {{channel_count}}.",
  "problems.TAG_IN_USE_BARE": "This Tag is still assigned.",
  "form.error.details": "Details",
  "form.error.copy": "Copy details",
  "common.requestId": "Request ID",
  "common.copy.success": "Copied",
  "common.copy.failed": "Copy failed",
  "common.retry": "Retry the load",
};

function t(key: string, options?: Record<string, string>) {
  const template = dictionary[key] ?? key;
  if (!options) return template;
  return template.replace(/\{\{(\w+)\}\}/g, (_, name: string) => options[name] ?? "");
}

function stubDomApis() {
  Object.defineProperty(window, "matchMedia", {
    writable: true,
    value: (query: string) => ({
      matches: false,
      media: query,
      addEventListener: vi.fn(),
      removeEventListener: vi.fn(),
    }),
  });
  class ResizeObserverStub {
    observe() {}
    unobserve() {}
    disconnect() {}
  }
  globalThis.ResizeObserver = ResizeObserverStub;
}

function resetNotifications() {
  const state = notificationsStore.getState();
  for (const item of [...state.notifications, ...state.queue]) {
    notifications.hide(item.id);
  }
  notifications.clean();
}

function renderNotifications() {
  render(createElement(MantineProvider, { env: "test" }, createElement(ConsoleNotifications)));
}

describe("presentProblemNotification", () => {
  beforeEach(() => {
    stubDomApis();
    copy.text.mockClear();
    resetNotifications();
  });

  afterEach(() => {
    resetNotifications();
    cleanup();
  });

  it("shows the localized problem as the title and copies the detail, request id, and field line", async () => {
    renderNotifications();
    presentProblemNotification(
      t,
      new ApiError(409, "USER_GROUP_KEY_DUPLICATE", "User Group key already exists", "req-42"),
      { unmapped: [{ field: "host", message: "Bad host" }] },
    );

    expect(await screen.findAllByRole("alert")).toHaveLength(1);
    const title = screen.getByText("That user group key is taken.");
    expect(title.closest("details")).toBeNull();

    fireEvent.click(screen.getByText("Details"));
    const detail = screen.getByText("User Group key already exists");
    expect(detail.closest("details")).toBeTruthy();
    expect(screen.getByText("Request ID: req-42").closest("details")).toBeTruthy();
    expect(screen.getByText("host: Bad host").closest("details")).toBeTruthy();

    fireEvent.click(screen.getByRole("button", { name: "Copy details" }));
    await waitFor(() => {
      expect(copy.text).toHaveBeenCalledWith(
        "User Group key already exists\nRequest ID: req-42\nhost: Bad host",
      );
    });
  });

  it("shows a field name alone when the unmapped detail has no message", async () => {
    renderNotifications();
    presentProblemNotification(t, new ApiError(422, "NO_SUCH_CODE", "Request invalid", "req-7"), {
      unmapped: [{ field: "  host  " }],
    });

    fireEvent.click(await screen.findByText("Details"));
    expect(screen.getByText("host").closest("details")).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "Copy details" }));
    await waitFor(() => {
      expect(copy.text).toHaveBeenCalledWith("Request invalid\nRequest ID: req-7\nhost");
    });
  });

  it("shows the message alone when the unmapped detail has no field", async () => {
    renderNotifications();
    presentProblemNotification(t, new ApiError(422, "NO_SUCH_CODE", "", null), {
      unmapped: [{ message: "  Bad host  " }],
    });

    fireEvent.click(await screen.findByText("Details"));
    expect(screen.getByText("Bad host").closest("details")).toBeTruthy();
    expect(screen.queryByText("Something went wrong. Try again.")?.closest("details")).toBeNull();
    fireEvent.click(screen.getByRole("button", { name: "Copy details" }));
    await waitFor(() => {
      expect(copy.text).toHaveBeenCalledWith("Bad host");
    });
  });

  it("uses the code when an unmapped detail has neither field nor message", async () => {
    renderNotifications();
    presentProblemNotification(t, new ApiError(422, "NO_SUCH_CODE", "Request invalid", null), {
      unmapped: [{ code: "  required  " }],
    });

    fireEvent.click(await screen.findByText("Details"));
    expect(screen.getByText("required").closest("details")).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "Copy details" }));
    await waitFor(() => {
      expect(copy.text).toHaveBeenCalledWith("Request invalid\nrequired");
    });
  });

  it("pairs a field with its code when the message is missing and drops a blank detail", async () => {
    renderNotifications();
    presentProblemNotification(t, new ApiError(422, "NO_SUCH_CODE", "Request invalid", null), {
      unmapped: [
        { field: "host", code: "required" },
        { field: "name", message: "Bad name", code: "other" },
        { field: " ", message: " ", code: " " },
      ],
    });

    fireEvent.click(await screen.findByText("Details"));
    expect(screen.getByText("host: required").closest("details")).toBeTruthy();
    expect(screen.getByText("name: Bad name").closest("details")).toBeTruthy();
    expect(screen.queryByText("name: other")).toBeNull();
    expect(screen.queryByText("host")).toBeNull();
    fireEvent.click(screen.getByRole("button", { name: "Copy details" }));
    await waitFor(() => {
      expect(copy.text).toHaveBeenCalledWith(
        "Request invalid\nhost: required\nname: Bad name",
      );
    });
  });

  it("offers a retry control on the error notification and runs that action once", async () => {
    const onRetry = vi.fn();
    renderNotifications();
    presentProblemNotification(
      t,
      new ApiError(500, "NO_SUCH_CODE", "Raw English detail", "req-9"),
      { onRetry },
    );

    expect(await screen.findAllByRole("alert")).toHaveLength(1);
    const title = screen.getByText("Something went wrong. Try again.");
    expect(title.closest("details")).toBeNull();
    const retry = screen.getByRole("button", { name: "Retry the load" });
    expect(retry.closest("details")).toBeNull();
    fireEvent.click(retry);
    expect(onRetry).toHaveBeenCalledTimes(1);

    fireEvent.click(screen.getByText("Details"));
    expect(screen.getByText("Raw English detail").closest("details")).toBeTruthy();
  });

  it("offers retry when the failure has nothing to disclose", async () => {
    const onRetry = vi.fn();
    renderNotifications();
    presentProblemNotification(t, new Error("socket hang up"), { onRetry });

    expect(await screen.findAllByRole("alert")).toHaveLength(1);
    expect(screen.getByText("Something went wrong. Try again.").closest("details")).toBeNull();
    expect(screen.queryByText("Details")).toBeNull();
    expect(screen.queryByText("socket hang up")).toBeNull();
    fireEvent.click(screen.getByRole("button", { name: "Retry the load" }));
    expect(onRetry).toHaveBeenCalledTimes(1);
  });

  it("states both TAG_IN_USE counts in the title and leaves the server detail in the disclosure", async () => {
    renderNotifications();
    presentProblemNotification(
      t,
      new ApiError(409, "TAG_IN_USE", "Tag is still assigned", "req-3", {
        entity_count: 2,
        channel_count: 0,
      }),
    );

    expect(await screen.findAllByRole("alert")).toHaveLength(1);
    const title = screen.getByText("This Tag is still assigned: Entities 2, Channels 0.");
    expect(title.closest("details")).toBeNull();
    expect(screen.queryByRole("button", { name: "Retry the load" })).toBeNull();
    fireEvent.click(screen.getByText("Details"));
    expect(screen.getByText("Tag is still assigned").closest("details")).toBeTruthy();
  });

  it("keeps unmapped lines in the disclosure when retry is also offered", async () => {
    const onRetry = vi.fn();
    renderNotifications();
    presentProblemNotification(t, new ApiError(422, "NO_SUCH_CODE", "Request invalid", "req-1"), {
      unmapped: [{ field: "host", message: "Bad host" }],
      onRetry,
    });

    expect(await screen.findAllByRole("alert")).toHaveLength(1);
    fireEvent.click(screen.getByRole("button", { name: "Retry the load" }));
    expect(onRetry).toHaveBeenCalledTimes(1);
    fireEvent.click(screen.getByText("Details"));
    expect(screen.getByText("host: Bad host").closest("details")).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "Copy details" }));
    await waitFor(() => {
      expect(copy.text).toHaveBeenCalledWith("Request invalid\nRequest ID: req-1\nhost: Bad host");
    });
  });
});
