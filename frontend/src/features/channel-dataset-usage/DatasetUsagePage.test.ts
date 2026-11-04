/** @vitest-environment jsdom */

import { MantineProvider } from "@mantine/core";
import { notifications, notificationsStore } from "@mantine/notifications";
import { act, cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { createElement, type ReactNode } from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { ApiError } from "@/lib/api";
import en from "@/locales/en-US/common.json";
import zh from "@/locales/zh-CN/common.json";
import { ConsoleNotifications } from "@/providers/notification-provider";

const copy = en as Record<string, string>;
const zhCopy = zh as Record<string, string>;

const USAGE_KEYS = [
  "channelDatasetUsage.title",
  "channelDatasetUsage.description",
  "channelDatasetUsage.used",
  "channelDatasetUsage.ceiling",
  "channelDatasetUsage.over",
  "channelDatasetUsage.refused",
  "channelDatasetUsage.remain",
] as const;

const getDatasetCapacity = vi.hoisted(() => vi.fn());

vi.mock("@/features/channels/api", () => ({
  getDatasetCapacity: (...args: unknown[]) => getDatasetCapacity(...args),
}));

vi.mock("@/features/branding/BrandingProvider", () => ({
  useBranding: () => ({ brandName: "Refraq" }),
}));

vi.mock("next/navigation", () => ({
  usePathname: () => "/console/channel-dataset-usage",
  useRouter: () => ({ push: vi.fn(), replace: vi.fn(), refresh: vi.fn() }),
  useSearchParams: () => new URLSearchParams(),
}));

vi.mock("next/link", () => ({
  default: ({ href, children }: { href: string; children?: ReactNode }) =>
    createElement("a", { href }, children),
  useLinkStatus: () => ({ pending: false }),
}));

vi.mock("@refinedev/core", () => ({
  useTranslate: () => (key: string, options?: Record<string, unknown>) => {
    const template = copy[key] ?? key;
    if (!options) return template;
    return template.replace(/\{\{(\w+)\}\}/g, (_, name: string) => String(options[name] ?? ""));
  },
  useNotification: () => ({ open: vi.fn() }),
  useCan: () => ({ data: { can: true } }),
  usePermissions: () => ({ data: ["channel:read"] as string[] }),
  useBreadcrumb: () => ({ breadcrumbs: [] }),
}));

const GIB = 1024 ** 3;

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
  return createElement(MantineProvider, { env: "test" }, createElement(ConsoleNotifications), node);
}

async function renderPage() {
  const { DatasetUsagePage } = await import("@/features/channel-dataset-usage/DatasetUsagePage");
  render(shell(createElement(DatasetUsagePage)));
}

function bar(): HTMLElement {
  const node = document.querySelector("[data-capacity-bar]");
  if (!(node instanceof HTMLElement)) throw new Error("capacity bar missing");
  return node;
}

function tipLines(): string[] {
  const tip = document.querySelector("[data-capacity-tip]");
  if (!(tip instanceof HTMLElement)) return [];
  return [...tip.children].map((child) => child.textContent ?? "");
}

describe("DatasetUsagePage", () => {
  beforeEach(() => {
    stubDomApis();
    getDatasetCapacity.mockReset();
    resetNotifications();
  });

  afterEach(() => {
    cleanup();
    resetNotifications();
  });

  it("shows the under-ceiling lines on hover and on focus, and no second segment", async () => {
    getDatasetCapacity.mockResolvedValue({
      used_bytes: 50 * GIB,
      ceiling_bytes: 100 * GIB,
    });
    await renderPage();

    expect(await screen.findByRole("heading", { name: "Dataset usage" })).toBeTruthy();
    expect(
      screen.getByText("Site-wide size of channel dataset tables against the ceiling."),
    ).toBeTruthy();
    const control = bar();
    expect(control.tabIndex).toBe(0);
    expect(screen.queryByText("Used 50 GB")).toBeNull();
    expect(document.querySelector("[data-capacity-over]")).toBeNull();
    expect(document.querySelector("[data-capacity-tick]")?.textContent).toBe("");
    expect(document.querySelector("[data-capacity-fill]")?.getAttribute("style")).toContain(
      "width: 50%",
    );

    fireEvent.mouseEnter(control);
    expect(tipLines()).toEqual([
      "Used 50 GB",
      "Ceiling 100 GB",
      "Another dataset can still be created, and a load in progress can continue. 50 GB remain before refusal.",
    ]);

    fireEvent.mouseLeave(control);
    expect(screen.queryByText("Used 50 GB")).toBeNull();

    fireEvent.focus(control);
    expect(tipLines()).toEqual([
      "Used 50 GB",
      "Ceiling 100 GB",
      "Another dataset can still be created, and a load in progress can continue. 50 GB remain before refusal.",
    ]);
    expect(screen.queryByText("Over")).toBeNull();
  });

  it("keeps the tip while hover or focus still holds", async () => {
    getDatasetCapacity.mockResolvedValue({
      used_bytes: 50 * GIB,
      ceiling_bytes: 100 * GIB,
    });
    await renderPage();
    const control = await waitFor(() => bar());

    fireEvent.focus(control);
    fireEvent.mouseLeave(control);
    expect(tipLines()).toEqual([
      "Used 50 GB",
      "Ceiling 100 GB",
      "Another dataset can still be created, and a load in progress can continue. 50 GB remain before refusal.",
    ]);

    fireEvent.mouseEnter(control);
    fireEvent.blur(control);
    expect(tipLines()).toEqual([
      "Used 50 GB",
      "Ceiling 100 GB",
      "Another dataset can still be created, and a load in progress can continue. 50 GB remain before refusal.",
    ]);

    fireEvent.mouseLeave(control);
    expect(screen.queryByText("Used 50 GB")).toBeNull();
  });

  it("stops the fill at the tick when used bytes equal the ceiling", async () => {
    getDatasetCapacity.mockResolvedValue({
      used_bytes: 100 * GIB,
      ceiling_bytes: 100 * GIB,
    });
    await renderPage();
    const control = await waitFor(() => bar());
    expect(document.querySelector("[data-capacity-over]")).toBeNull();
    expect(document.querySelector("[data-capacity-fill]")?.getAttribute("style")).toContain(
      "width: 100%",
    );
    fireEvent.focus(control);
    expect(tipLines()).toEqual([
      "Used 100 GB",
      "Ceiling 100 GB",
      "Existing tables stay. Creating or loading another dataset is refused.",
    ]);
  });

  it("draws a second segment past the tick when used bytes pass the ceiling", async () => {
    getDatasetCapacity.mockResolvedValue({
      used_bytes: 150 * GIB,
      ceiling_bytes: 100 * GIB,
    });
    await renderPage();
    const control = await waitFor(() => bar());
    expect(document.querySelector("[data-capacity-fill]")?.getAttribute("style")).toContain(
      "width: 100%",
    );
    expect(document.querySelector("[data-capacity-over]")?.getAttribute("style")).toContain(
      "width: 50%",
    );
    expect(document.querySelector("[data-capacity-tick]")?.textContent).toBe("");
    fireEvent.focus(control);
    expect(tipLines()).toEqual([
      "Used 150 GB",
      "Ceiling 100 GB",
      "Over",
      "Existing tables stay. Creating or loading another dataset is refused.",
    ]);
  });

  it("stays loading until the capacity read settles", async () => {
    let settle: (value: { used_bytes: number; ceiling_bytes: number }) => void = () => {};
    getDatasetCapacity.mockReturnValue(
      new Promise((resolve) => {
        settle = resolve;
      }),
    );
    await renderPage();
    expect(screen.getByRole("heading", { name: "Dataset usage" })).toBeTruthy();
    expect(document.querySelector("[data-capacity-bar]")).toBeNull();
    expect(document.querySelector(".mantine-Skeleton-root")).toBeTruthy();
    await act(async () => {
      settle({ used_bytes: 0, ceiling_bytes: 100 * GIB });
    });
    expect(bar().tabIndex).toBe(0);
    expect(document.querySelector(".mantine-Skeleton-root")).toBeNull();
  });

  it("reloads from the unloaded page after a failed capacity read", async () => {
    getDatasetCapacity
      .mockRejectedValueOnce(new ApiError(500, "INTERNAL_ERROR", "capacity down", "req-cap"))
      .mockResolvedValueOnce({ used_bytes: 0, ceiling_bytes: 100 * GIB });
    await renderPage();

    const status = await screen.findByRole("button", { name: "Not loaded" });
    expect(document.querySelector("[data-page-scroll]")?.contains(status)).toBe(true);
    const alerts = screen.getAllByRole("alert");
    expect(alerts).toHaveLength(1);
    expect(alerts[0]?.textContent).toContain("Something went wrong. Try again.");
    expect(alerts[0]?.textContent).toContain("req-cap");
    expect(screen.getByRole("button", { name: "Retry" })).toBeTruthy();

    fireEvent.click(status);
    const control = await waitFor(() => bar());
    expect(screen.queryByRole("button", { name: "Not loaded" })).toBeNull();
    expect(getDatasetCapacity).toHaveBeenCalledTimes(2);
    fireEvent.focus(control);
    expect(tipLines()).toEqual([
      "Used 0 GB",
      "Ceiling 100 GB",
      "Another dataset can still be created, and a load in progress can continue. 100 GB remain before refusal.",
    ]);
  });

  it("does not show the unloaded badge when the session has expired", async () => {
    getDatasetCapacity.mockRejectedValue(
      new ApiError(401, "AUTH_UNAUTHENTICATED", "signed out", "req-auth"),
    );
    await renderPage();
    await waitFor(() => {
      expect(getDatasetCapacity).toHaveBeenCalledTimes(1);
      expect(document.querySelector(".mantine-Skeleton-root")).toBeNull();
    });
    expect(screen.getByRole("heading", { name: "Dataset usage" })).toBeTruthy();
    expect(screen.queryByRole("button", { name: "Not loaded" })).toBeNull();
    expect(screen.queryAllByRole("alert")).toHaveLength(0);
    expect(document.querySelector("[data-capacity-bar]")).toBeNull();
  });
});

describe("dataset usage copy", () => {
  it("keeps the English capacity-bar sentences", () => {
    expect(copy["channelDatasetUsage.title"]).toBe("Dataset usage");
    expect(copy["channelDatasetUsage.description"]).toBe(
      "Site-wide size of channel dataset tables against the ceiling.",
    );
    expect(copy["channelDatasetUsage.used"]).toBe("Used {{used}} GB");
    expect(copy["channelDatasetUsage.ceiling"]).toBe("Ceiling {{ceiling}} GB");
    expect(copy["channelDatasetUsage.over"]).toBe("Over");
    expect(copy["channelDatasetUsage.refused"]).toBe(
      "Existing tables stay. Creating or loading another dataset is refused.",
    );
    expect(copy["channelDatasetUsage.remain"]).toBe(
      "Another dataset can still be created, and a load in progress can continue. {{remain}} GB remain before refusal.",
    );
    for (const key of USAGE_KEYS) {
      expect(typeof zhCopy[key]).toBe("string");
      expect(zhCopy[key]?.length).toBeGreaterThan(0);
    }
  });
});
