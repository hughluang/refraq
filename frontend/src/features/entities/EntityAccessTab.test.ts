/** @vitest-environment jsdom */

import { MantineProvider } from "@mantine/core";
import { notifications, notificationsStore } from "@mantine/notifications";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { createElement, type ReactNode } from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { getAccessSummary } from "@/features/entities/accessApi";
import { EntityAccessTab } from "@/features/entities/EntityAccessTab";
import type { AccessSummary } from "@/features/entities/accessTypes";
import { listAllSubjectAttributes } from "@/features/subjects/api";
import { ApiError } from "@/lib/api";
import { ConsoleNotifications } from "@/providers/notification-provider";

const translate = vi.hoisted(() => (key: string) => key);

vi.mock("@refinedev/core", () => ({
  useTranslate: () => translate,
  useNotification: () => ({ open: vi.fn() }),
}));

vi.mock("@/features/entities/accessApi", async () => {
  const actual = await vi.importActual<typeof import("@/features/entities/accessApi")>(
    "@/features/entities/accessApi",
  );
  return { ...actual, getAccessSummary: vi.fn() };
});

vi.mock("@/features/subjects/api", async () => {
  const actual = await vi.importActual<typeof import("@/features/subjects/api")>(
    "@/features/subjects/api",
  );
  return { ...actual, listAllSubjectAttributes: vi.fn() };
});

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
  if (!Element.prototype.scrollIntoView) {
    Element.prototype.scrollIntoView = () => {};
  }
  vi.stubGlobal(
    "fetch",
    vi.fn(async () => new Response(JSON.stringify({ items: [] }), { status: 200 })),
  );
}

function resetNotifications() {
  const state = notificationsStore.getState();
  for (const item of [...state.notifications, ...state.queue]) {
    notifications.hide(item.id);
  }
  notifications.clean();
}

const summary: AccessSummary = {
  entity_id: "ent_1",
  head_version_id: "ver_1",
  policy_revision: 1,
  views: {
    state: "ready",
    revision: 1,
    single_profile_views: 1,
    combinations: 0,
    combination_limit: 64,
    subjects_over_limit: 0,
    latest_job_id: null,
  },
  ladders: [],
  profiles: [],
  grants: [],
  restrictions: [],
};

function shell(node: ReactNode) {
  return createElement(
    MantineProvider,
    { env: "test" },
    createElement(ConsoleNotifications),
    node,
  );
}

function renderTab(entityId = "ent_1") {
  return render(
    shell(createElement(EntityAccessTab, { entityId, canPreviewRows: false })),
  );
}

describe("EntityAccessTab load", () => {
  beforeEach(() => {
    stubDomApis();
    resetNotifications();
    vi.mocked(getAccessSummary).mockReset();
    vi.mocked(listAllSubjectAttributes).mockReset();
    vi.mocked(listAllSubjectAttributes).mockResolvedValue([]);
  });

  afterEach(() => {
    cleanup();
    resetNotifications();
    vi.unstubAllGlobals();
  });

  it("notifies once and leaves every empty section unloaded", async () => {
    vi.mocked(getAccessSummary).mockRejectedValue(
      new ApiError(500, "NO_SUCH_CODE", "Database unavailable", "req-17"),
    );
    renderTab();

    expect(await screen.findAllByRole("alert")).toHaveLength(1);
    expect(screen.getAllByRole("button", { name: "status.unloaded" })).toHaveLength(3);
    expect(screen.queryByText("entities.access.summary.title")).toBeNull();
    expect(screen.queryByText("common.error")).toBeNull();
    for (const table of screen.getAllByRole("table")) {
      expect(table.querySelector("[role='alert']")).toBeNull();
    }

    fireEvent.click(screen.getByText("form.error.details"));
    expect(screen.getAllByText("Database unavailable")).toHaveLength(1);
    expect(screen.getByText("common.requestId: req-17").closest("details")).toBeTruthy();

    fireEvent.click(screen.getByRole("button", { name: "common.retry" }));
    await waitFor(() => {
      expect(getAccessSummary).toHaveBeenCalledTimes(2);
    });
    expect(getAccessSummary).toHaveBeenLastCalledWith("ent_1");
  });

  it("notifies a later summary failure and keeps the sections that already have a summary", async () => {
    vi.mocked(getAccessSummary).mockResolvedValueOnce(summary);
    const view = renderTab();
    expect(await screen.findByText("entities.access.summary.title")).toBeTruthy();
    expect(screen.queryByRole("alert")).toBeNull();

    vi.mocked(getAccessSummary).mockRejectedValue(
      new ApiError(500, "NO_SUCH_CODE", "Database unavailable", "req-18"),
    );
    view.rerender(
      shell(createElement(EntityAccessTab, { entityId: "ent_2", canPreviewRows: false })),
    );

    expect(await screen.findAllByRole("alert")).toHaveLength(1);
    expect(screen.getByText("entities.access.summary.title")).toBeTruthy();
    expect(screen.queryByRole("button", { name: "status.unloaded" })).toBeNull();
    fireEvent.click(screen.getByText("form.error.details"));
    expect(screen.getByText("Database unavailable").closest("details")).toBeTruthy();
    expect(screen.getByText("common.requestId: req-18").closest("details")).toBeTruthy();
    for (const table of screen.getAllByRole("table")) {
      expect(table.querySelector("[role='alert']")).toBeNull();
    }
  });

  it("notifies an options failure without unloading the summary", async () => {
    vi.mocked(getAccessSummary).mockResolvedValue(summary);
    vi.mocked(listAllSubjectAttributes).mockRejectedValue(
      new ApiError(500, "NO_SUCH_CODE", "Attributes offline", "req-19"),
    );
    renderTab();

    expect(await screen.findByText("entities.access.summary.title")).toBeTruthy();
    expect(await screen.findAllByRole("alert")).toHaveLength(1);
    expect(screen.queryByRole("button", { name: "status.unloaded" })).toBeNull();
    expect(screen.getByRole("alert").textContent).toContain("problems.unknown");
    fireEvent.click(screen.getByText("form.error.details"));
    expect(screen.getByText("Attributes offline").closest("details")).toBeTruthy();
    expect(screen.getByText("common.requestId: req-19").closest("details")).toBeTruthy();

    fireEvent.click(screen.getByRole("button", { name: "common.retry" }));
    await waitFor(() => {
      expect(listAllSubjectAttributes).toHaveBeenCalledTimes(2);
    });
    expect(getAccessSummary).toHaveBeenCalledTimes(1);
  });
});
