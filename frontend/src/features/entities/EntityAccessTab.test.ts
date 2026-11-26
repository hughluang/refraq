/** @vitest-environment jsdom */

import { MantineProvider } from "@mantine/core";
import { notifications, notificationsStore } from "@mantine/notifications";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { createElement, type ReactNode } from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { EntityAccessTab } from "@/features/entities/EntityAccessTab";
import type { AccessSummary } from "@/features/entities/accessTypes";
import {
  manualLiveSchedule,
  memoryAccessPort,
  type AccessPort,
  type LiveSchedulePort,
} from "@/features/entities/accessWorkbench";
import { ApiError } from "@/lib/api";
import { ConsoleNotifications } from "@/providers/notification-provider";

const translate = vi.hoisted(() => (key: string) => key);

vi.mock("@refinedev/core", () => ({
  useTranslate: () => translate,
  useNotification: () => ({ open: vi.fn() }),
}));

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

const populatedSummary: AccessSummary = {
  entity_id: "ent_1",
  head_version_id: "ver_1",
  policy_revision: 1,
  views: {
    state: "ready",
    revision: 1,
    single_profile_views: 1,
    combinations: 1,
    combination_limit: 64,
    subjects_over_limit: 0,
    latest_job_id: null,
  },
  ladders: [
    {
      attribute_id: "att_email",
      attribute_name: "email",
      attribute_display_name: "Email",
      type: "string",
      value_type: "string",
      accepted_masks: ["clear", "email", "redact"],
      operators: ["eq", "neq", "contains", "is_null", "is_not_null"],
      compatible_subject_attributes: [],
      levels: [
        { key: "clear", mode: "clear" },
        { key: "masked", mode: { type: "email" } },
      ],
    },
  ],
  profiles: [
    {
      id: "prf_1",
      entity_id: "ent_1",
      key: "analyst",
      name: "Analyst",
      description: null,
      columns: [{ attribute_id: "att_email", attribute_name: "email", level: "masked" }],
      broken: false,
      broken_reasons: [],
    },
  ],
  grants: [
    {
      id: "grt_1",
      subject: { type: "user", id: "usr_ada", display_name: "Ada" },
      profile_id: "prf_1",
      row_rule: null,
      actions: ["read"],
      status: "active",
      valid_until: null,
      locked: false,
      broken: false,
      broken_reasons: [],
      warnings: [],
    },
  ],
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

function renderTab(props: {
  entityId?: string;
  canPreviewRows?: boolean;
  port: AccessPort;
  schedule?: LiveSchedulePort;
}) {
  return render(
    shell(
      createElement(EntityAccessTab, {
        entityId: props.entityId ?? "ent_1",
        canPreviewRows: props.canPreviewRows ?? false,
        port: props.port,
        schedule: props.schedule ?? manualLiveSchedule(),
      }),
    ),
  );
}

describe("EntityAccessTab", () => {
  beforeEach(() => {
    stubDomApis();
    resetNotifications();
  });

  afterEach(() => {
    cleanup();
    resetNotifications();
    vi.unstubAllGlobals();
  });

  it("notifies once on initial load failure and retries via common.retry", async () => {
    const port = memoryAccessPort(populatedSummary);
    let attempts = 0;
    port.loadSummary = async () => {
      attempts += 1;
      throw new ApiError(500, "NO_SUCH_CODE", "Database unavailable", "req-17");
    };

    renderTab({ port });

    expect(await screen.findAllByRole("alert")).toHaveLength(1);
    expect(screen.getByRole("button", { name: "common.retry" })).toBeTruthy();

    fireEvent.click(screen.getByText("form.error.details"));
    expect(screen.getAllByText("Database unavailable")).toHaveLength(1);
    expect(screen.getByText("common.requestId: req-17").closest("details")).toBeTruthy();

    fireEvent.click(screen.getByRole("button", { name: "common.retry" }));
    await waitFor(() => {
      expect(attempts).toBe(2);
    });
  });

  it("notifies on a later entity failure while keeping the loaded workbench", async () => {
    const port = memoryAccessPort(populatedSummary);
    const origLoad = port.loadSummary;
    port.loadSummary = async (entityId) => {
      if (entityId === "ent_2") {
        throw new ApiError(500, "NO_SUCH_CODE", "Database unavailable", "req-18");
      }
      return origLoad(entityId);
    };

    const view = renderTab({ entityId: "ent_1", port });
    expect(await screen.findByText("Ada")).toBeTruthy();
    expect(screen.queryByRole("alert")).toBeNull();

    view.rerender(
      shell(
        createElement(EntityAccessTab, {
          entityId: "ent_2",
          canPreviewRows: false,
          port,
          schedule: manualLiveSchedule(),
        }),
      ),
    );

    expect(await screen.findAllByRole("alert")).toHaveLength(1);
    expect(screen.getByRole("button", { name: "common.retry" })).toBeTruthy();
  });

  it("renders topology + specimen lens and opens inline inspector on node click", async () => {
    const port = memoryAccessPort(populatedSummary);
    renderTab({ port });

    expect(await screen.findByText("Ada")).toBeTruthy();
    expect(screen.getAllByText("Analyst").length).toBeGreaterThanOrEqual(1);
    expect(screen.getByText("entities.access.workbench.lensMatrixTitle")).toBeTruthy();

    fireEvent.click(screen.getByText("Ada"));
    expect(await screen.findByText("entities.access.grants.save")).toBeTruthy();
  });
});
