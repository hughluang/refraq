/** @vitest-environment jsdom */

import { MantineProvider } from "@mantine/core";
import { notifications, notificationsStore } from "@mantine/notifications";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { createElement, type ReactNode } from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { ApiError } from "@/lib/api";
import en from "@/locales/en-US/common.json";
import { ConsoleNotifications } from "@/providers/notification-provider";

const getStructureDiff = vi.hoisted(() => vi.fn());
const getSource = vi.hoisted(() => vi.fn());

const copy = en as Record<string, string>;

function translate(key: string) {
  return copy[key] ?? key;
}

vi.mock("@refinedev/core", () => ({
  useTranslate: () => translate,
  useBreadcrumb: () => ({ breadcrumbs: [] }),
}));

vi.mock("next/link", () => ({
  default: ({ href, children }: { href: string; children: ReactNode }) =>
    createElement("a", { href }, children),
  useLinkStatus: () => ({ pending: false }),
}));

vi.mock("next/navigation", () => ({
  usePathname: () => "/console/sources/src_1/structure-diffs/diff_1",
  useRouter: () => ({ push: vi.fn(), replace: vi.fn(), refresh: vi.fn() }),
  useSearchParams: () => new URLSearchParams(),
}));

vi.mock("@/features/branding/BrandingProvider", () => ({
  useBranding: () => ({ brandName: "Refraq" }),
}));

vi.mock("@/providers/session-store", () => ({
  useSessionStore: (selector: (state: { user: null }) => unknown) =>
    selector({ user: null }),
}));

vi.mock("@/features/sources/api/structure-diffs", () => ({
  getStructureDiff,
}));

vi.mock("@/features/sources/api/sources", () => ({
  getSource,
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
}

function resetNotifications() {
  const state = notificationsStore.getState();
  for (const item of [...state.notifications, ...state.queue]) {
    notifications.hide(item.id);
  }
  notifications.clean();
}

function shell(node: ReactNode) {
  return createElement(
    MantineProvider,
    { env: "test" },
    createElement(ConsoleNotifications),
    node,
  );
}

describe("StructureDiffDetail load", () => {
  beforeEach(() => {
    stubDomApis();
    getStructureDiff.mockReset();
    getSource.mockReset();
    getSource.mockResolvedValue({ source: { name: "Warehouse" } });
    resetNotifications();
  });

  afterEach(() => {
    cleanup();
    resetNotifications();
  });

  it("shows unloaded and one notice with the request id when the diff fails to load", async () => {
    getStructureDiff.mockRejectedValue(
      new ApiError(500, "NO_SUCH_CODE", "database offline", "req-18"),
    );
    const { StructureDiffDetail } = await import(
      "@/features/sources/structure-diffs/StructureDiffDetail"
    );
    render(
      shell(
        createElement(StructureDiffDetail, { sourceId: "src_1", diffId: "diff_1" }),
      ),
    );

    const heading = await screen.findByRole("heading", { name: /Structure Diff detail/ });
    expect(document.querySelector("[data-page-header]")?.contains(heading)).toBe(true);
    expect(screen.getByRole("button", { name: "Not loaded" })).toBeTruthy();
    expect(screen.queryByRole("heading", { name: "Page not found" })).toBeNull();
    expect(screen.queryByText("Something went wrong")).toBeNull();

    expect(await screen.findAllByRole("alert")).toHaveLength(1);
    fireEvent.click(screen.getByText("Details"));
    expect(screen.getByText("database offline").closest("details")).toBeTruthy();
    expect(screen.getByText("Request ID: req-18").closest("details")).toBeTruthy();

    fireEvent.click(screen.getByRole("button", { name: "Retry" }));
    await waitFor(() => expect(getStructureDiff).toHaveBeenCalledTimes(2));
  });

  it("shows a source mismatch as a notice and does not notify", async () => {
    getStructureDiff.mockResolvedValue({
      structure_diff: {
        id: "diff_1",
        source_id: "src_other",
        job_id: "job_1",
        class: "additive",
        counts: {},
        created_at: "2026-09-10T04:00:00Z",
      },
    });
    const { StructureDiffDetail } = await import(
      "@/features/sources/structure-diffs/StructureDiffDetail"
    );
    render(
      shell(
        createElement(StructureDiffDetail, { sourceId: "src_1", diffId: "diff_1" }),
      ),
    );

    expect(
      await screen.findByText("This Diff does not belong to the current Source"),
    ).toBeTruthy();
    expect(screen.queryByRole("button", { name: "Not loaded" })).toBeNull();
    expect(screen.queryByRole("button", { name: "Retry" })).toBeNull();
    expect(screen.queryByRole("heading", { name: "Page not found" })).toBeNull();
    expect(screen.queryAllByRole("alert")).toHaveLength(0);
    expect(getStructureDiff).toHaveBeenCalledTimes(1);
  });
});
