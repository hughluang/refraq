/** @vitest-environment jsdom */

import { MantineProvider } from "@mantine/core";
import { notifications, notificationsStore } from "@mantine/notifications";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { createElement, type ReactNode } from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { previewAccess } from "@/features/entities/accessApi";
import { AccessPreviewSection } from "@/features/entities/AccessPreviewSection";
import type { AccessRun } from "@/features/entities/accessSession";
import type { UserRow } from "@/features/users/types";
import { listUsers } from "@/features/users/api";
import { ApiError } from "@/lib/api";
import { ConsoleNotifications } from "@/providers/notification-provider";

const translate = vi.hoisted(() => (key: string) => key);

vi.mock("@refinedev/core", () => ({
  useTranslate: () => translate,
}));

vi.mock("@/features/entities/accessApi", () => ({
  previewAccess: vi.fn(),
}));

vi.mock("@/features/users/api", () => ({
  listUsers: vi.fn(),
}));

const ada: UserRow = {
  id: "user_1",
  account: "ada",
  display_name: "Ada Lovelace",
  email: null,
  locale: "en-US",
  display_timezone: null,
  role_id: null,
  role_key: null,
  role_name: null,
  status: "active",
  identity_source: "local",
  last_login_at: null,
};

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
  if (document.fonts == null) {
    Object.defineProperty(document, "fonts", {
      configurable: true,
      value: { addEventListener() {}, removeEventListener() {} },
    });
  }
}

function resetNotifications() {
  const state = notificationsStore.getState();
  for (const item of [...state.notifications, ...state.queue]) {
    notifications.hide(item.id);
  }
  notifications.clean();
}

const run: AccessRun = async (_id, _savedKey, work) => {
  await work();
  return true;
};

function shell(node: ReactNode) {
  return createElement(
    MantineProvider,
    { env: "test" },
    createElement(ConsoleNotifications),
    node,
  );
}

function previewRegion(): HTMLElement {
  const heading = screen.getByRole("heading", { name: "entities.access.preview" });
  let region: HTMLElement | null = heading;
  while (region && !region.textContent?.includes("entities.access.preview.run")) {
    region = region.parentElement;
  }
  if (!region) throw new Error("missing preview");
  return region;
}

async function chooseAda() {
  fireEvent.click(screen.getByRole("button", { name: "entities.access.expand" }));
  fireEvent.click(
    screen.getByRole("button", { name: "entities.access.subject.user", hidden: true }),
  );
  fireEvent.click(await screen.findByRole("option", { name: /Ada Lovelace/, hidden: true }));
}

describe("AccessPreviewSection", () => {
  beforeEach(() => {
    stubDomApis();
    resetNotifications();
    vi.mocked(listUsers).mockResolvedValue({
      items: [ada],
      total: 1,
      limit: 20,
      offset: 0,
    });
    vi.mocked(previewAccess).mockReset();
  });

  afterEach(() => {
    cleanup();
    resetNotifications();
  });

  it("notifies a failed run and clears the previous result", async () => {
    vi.mocked(previewAccess).mockResolvedValueOnce({
      policy_revision: 1,
      effective_grants: [],
      schema: {
        attributes: [{ name: "sku" }],
        withheld_field: null,
      },
      rows: { items: [{ sku: "ABC" }], total: 1 },
    });
    render(
      shell(
        createElement(AccessPreviewSection, {
          entityId: "ent_1",
          canPreviewRows: true,
          busyId: null,
          run,
        }),
      ),
    );
    await chooseAda();
    fireEvent.click(screen.getByRole("button", { name: "entities.access.preview.run", hidden: true }));
    expect(await screen.findByText("ABC")).toBeTruthy();
    expect(screen.getAllByText("sku").length).toBeGreaterThan(0);

    vi.mocked(previewAccess).mockRejectedValue(
      new ApiError(500, "NO_SUCH_CODE", "Preview failed", "req-21"),
    );
    fireEvent.click(screen.getByRole("button", { name: "entities.access.preview.run", hidden: true }));

    await waitFor(() => {
      expect(screen.queryByText("ABC")).toBeNull();
    });
    expect(screen.queryByText("sku")).toBeNull();
    expect(previewRegion().querySelector("[role='alert']")).toBeNull();
    expect(screen.getAllByRole("alert")).toHaveLength(1);
    fireEvent.click(screen.getByText("form.error.details"));
    expect(screen.getByText("Preview failed").closest("details")).toBeTruthy();
    expect(screen.getByText("common.requestId: req-21").closest("details")).toBeTruthy();
  });
});
