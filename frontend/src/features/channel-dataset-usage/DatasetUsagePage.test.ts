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

const LIST_KEYS = [
  "channelDatasetUsage.columns.channel",
  "channelDatasetUsage.columns.node",
  "channelDatasetUsage.columns.status",
  "channelDatasetUsage.columns.size",
  "channelDatasetUsage.columns.rows",
  "channelDatasetUsage.columns.created",
  "channelDatasetUsage.columns.expires",
  "channelDatasetUsage.status.loading",
  "channelDatasetUsage.status.ready",
] as const;

const getDatasetCapacity = vi.hoisted(() => vi.fn());
const listChannelDatasets = vi.hoisted(() => vi.fn());
const push = vi.hoisted(() => vi.fn());

vi.mock("@/features/channels/api", () => ({
  getDatasetCapacity: (...args: unknown[]) => getDatasetCapacity(...args),
  listChannelDatasets: (...args: unknown[]) => listChannelDatasets(...args),
}));

vi.mock("@/hooks/useFormatInstant", async () => {
  const datetime = await import("@/lib/datetime");
  const format = (value: string | null | undefined) =>
    datetime.formatInstant(value, { timeZone: "UTC", locale: "en-US" });
  return {
    useFormatInstant: () => format,
    useShowInstant: () => format,
  };
});

vi.mock("@/features/branding/BrandingProvider", () => ({
  useBranding: () => ({ brandName: "Refraq" }),
}));

vi.mock("next/navigation", () => ({
  usePathname: () => "/console/channel-dataset-usage",
  useRouter: () => ({ push, replace: vi.fn(), refresh: vi.fn() }),
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

function texts(row: HTMLTableRowElement): string[] {
  return [...row.querySelectorAll("td")].map((cell) => cell.textContent ?? "");
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
    listChannelDatasets.mockReset();
    listChannelDatasets.mockResolvedValue({ items: [], total: 0, limit: 50, offset: 0 });
    push.mockReset();
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

  it("lists datasets under the bar, linking only the channel cell", async () => {
    getDatasetCapacity.mockResolvedValue({
      used_bytes: 50 * GIB,
      ceiling_bytes: 100 * GIB,
    });
    listChannelDatasets.mockResolvedValue({
      items: [
        {
          id: "ds_ready",
          job_id: "job_01HZX",
          channel_id: "chn_01HZX",
          channel_name: "Order sync",
          node_id: "n_query",
          node_name: "Query orders",
          status: "ready",
          size_bytes: 68987912192,
          row_count: 120000,
          created_at: "2026-11-04T01:12:00Z",
          expires_at: "2026-11-05T01:12:00Z",
        },
        {
          id: "ds_loading",
          job_id: "job_loading",
          channel_id: null,
          channel_name: "",
          node_id: "n_load",
          node_name: "n_load",
          status: "loading",
          size_bytes: 0,
          row_count: 0,
          created_at: "2026-11-04T01:12:00Z",
          expires_at: null,
        },
      ],
      total: 2,
      limit: 50,
      offset: 0,
    });
    await renderPage();

    expect(await screen.findByRole("columnheader", { name: "Channel" })).toBeTruthy();
    expect(screen.getAllByRole("columnheader").map((node) => node.textContent)).toEqual([
      "Channel",
      "Node",
      "Status",
      "Size",
      "Rows",
      "Created",
      "Expires",
    ]);
    const control = bar();
    const header = screen.getByRole("columnheader", { name: "Channel" });
    expect(control.compareDocumentPosition(header) & Node.DOCUMENT_POSITION_FOLLOWING).toBe(
      Node.DOCUMENT_POSITION_FOLLOWING,
    );
    const link = screen.getByRole("link", { name: "Order sync" });
    expect(link.getAttribute("href")).toBe("/console/channels/chn_01HZX/runs/job_01HZX");
    const readyRow = link.closest("tr");
    if (!(readyRow instanceof HTMLTableRowElement)) throw new Error("ready row missing");
    expect(readyRow.querySelectorAll("a")).toHaveLength(1);
    expect(texts(readyRow).slice(1)).toEqual([
      "Query orders",
      "Ready",
      "64.3 GB",
      "120000",
      "11/4/2026, 1:12:00 AM",
      "11/5/2026, 1:12:00 AM",
    ]);
    fireEvent.click(readyRow);
    fireEvent.click(screen.getByText("Query orders"));
    expect(push).not.toHaveBeenCalled();

    const loadingNode = screen.getByText("n_load");
    const loadingRow = loadingNode.closest("tr");
    if (!(loadingRow instanceof HTMLTableRowElement)) throw new Error("loading row missing");
    expect(loadingRow.querySelector("a")).toBeNull();
    expect(texts(loadingRow)).toEqual([
      "",
      "n_load",
      "Loading",
      "0 GB",
      "0",
      "11/4/2026, 1:12:00 AM",
      "—",
    ]);
    expect(listChannelDatasets).toHaveBeenCalledWith({ limit: 50, offset: 0 });
    fireEvent.focus(control);
    expect(tipLines()).toEqual([
      "Used 50 GB",
      "Ceiling 100 GB",
      "Another dataset can still be created, and a load in progress can continue. 50 GB remain before refusal.",
    ]);
  });

  it("leaves the bar and shows the empty row without a create action", async () => {
    getDatasetCapacity.mockResolvedValue({
      used_bytes: 0,
      ceiling_bytes: 100 * GIB,
    });
    await renderPage();
    expect(await screen.findByText("No data")).toBeTruthy();
    expect(bar().tabIndex).toBe(0);
    const emptyRow = screen.getByText("No data").closest("tr");
    expect(emptyRow?.querySelector("a, button")).toBeNull();
    expect(screen.queryByRole("button", { name: /create/i })).toBeNull();
    expect(screen.queryByRole("link", { name: /create/i })).toBeNull();
  });

  it("stays loading until the capacity read and the list both settle", async () => {
    let settleCapacity: (value: { used_bytes: number; ceiling_bytes: number }) => void = () => {};
    let settleList: (value: { items: []; total: number; limit: number; offset: number }) => void =
      () => {};
    getDatasetCapacity.mockReturnValue(
      new Promise((resolve) => {
        settleCapacity = resolve;
      }),
    );
    listChannelDatasets.mockReturnValue(
      new Promise((resolve) => {
        settleList = resolve;
      }),
    );
    await renderPage();
    expect(document.querySelector("[data-capacity-bar]")).toBeNull();
    expect(document.querySelector(".mantine-Skeleton-root")).toBeTruthy();
    expect(screen.queryByRole("columnheader", { name: "Channel" })).toBeNull();
    await act(async () => {
      settleCapacity({ used_bytes: 0, ceiling_bytes: 100 * GIB });
    });
    expect(document.querySelector("[data-capacity-bar]")).toBeNull();
    expect(document.querySelector(".mantine-Skeleton-root")).toBeTruthy();
    await act(async () => {
      settleList({ items: [], total: 0, limit: 50, offset: 0 });
    });
    expect(bar().tabIndex).toBe(0);
    expect(screen.getByText("No data")).toBeTruthy();
    expect(document.querySelector(".mantine-Skeleton-root")).toBeNull();
  });

  it("reloads the capacity read and the list from the unloaded page", async () => {
    getDatasetCapacity
      .mockRejectedValueOnce(new ApiError(500, "INTERNAL_ERROR", "capacity down", "req-cap"))
      .mockResolvedValueOnce({ used_bytes: 0, ceiling_bytes: 100 * GIB });
    await renderPage();
    const status = await screen.findByRole("button", { name: "Not loaded" });
    expect(status.closest("tbody")).toBeNull();
    fireEvent.click(status);
    await waitFor(() => bar());
    expect(getDatasetCapacity).toHaveBeenCalledTimes(2);
    expect(listChannelDatasets).toHaveBeenCalledTimes(2);
  });

  it("keeps the bar and retries only the list when the list fails", async () => {
    getDatasetCapacity.mockResolvedValue({
      used_bytes: 10 * GIB,
      ceiling_bytes: 100 * GIB,
    });
    listChannelDatasets
      .mockRejectedValueOnce(new ApiError(500, "INTERNAL_ERROR", "list down", "req-list"))
      .mockResolvedValueOnce({
        items: [
          {
            id: "ds_ready",
            job_id: "job_01HZX",
            channel_id: "chn_01HZX",
            channel_name: "Order sync",
            node_id: "n_query",
            node_name: "Query orders",
            status: "ready",
            size_bytes: 0,
            row_count: 0,
            created_at: "2026-11-04T01:12:00Z",
            expires_at: null,
          },
        ],
        total: 1,
        limit: 50,
        offset: 0,
      });
    await renderPage();
    const control = await waitFor(() => bar());
    const unloaded = screen.getByRole("button", { name: "Not loaded" });
    expect(unloaded.closest("tbody")).toBeTruthy();
    expect(screen.getAllByRole("button", { name: "Not loaded" })).toHaveLength(1);
    const alerts = screen.getAllByRole("alert");
    expect(alerts).toHaveLength(1);
    expect(alerts[0]?.textContent).toContain("Something went wrong. Try again.");
    expect(alerts[0]?.textContent).toContain("req-list");
    fireEvent.focus(control);
    expect(tipLines()[0]).toBe("Used 10 GB");
    fireEvent.click(unloaded);
    expect(await screen.findByRole("link", { name: "Order sync" })).toBeTruthy();
    expect(getDatasetCapacity).toHaveBeenCalledTimes(1);
    expect(listChannelDatasets).toHaveBeenCalledTimes(2);
    expect(screen.getByText("0 GB")).toBeTruthy();
    expect(screen.getByText("—")).toBeTruthy();
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
    expect(copy["channelDatasetUsage.columns.channel"]).toBe("Channel");
    expect(copy["channelDatasetUsage.columns.node"]).toBe("Node");
    expect(copy["channelDatasetUsage.columns.status"]).toBe("Status");
    expect(copy["channelDatasetUsage.columns.size"]).toBe("Size");
    expect(copy["channelDatasetUsage.columns.rows"]).toBe("Rows");
    expect(copy["channelDatasetUsage.columns.created"]).toBe("Created");
    expect(copy["channelDatasetUsage.columns.expires"]).toBe("Expires");
    expect(copy["channelDatasetUsage.status.loading"]).toBe("Loading");
    expect(copy["channelDatasetUsage.status.ready"]).toBe("Ready");
    for (const key of USAGE_KEYS) {
      expect(typeof zhCopy[key]).toBe("string");
      expect(zhCopy[key]?.length).toBeGreaterThan(0);
    }
    for (const key of LIST_KEYS) {
      expect(typeof zhCopy[key]).toBe("string");
      expect(zhCopy[key]?.length).toBeGreaterThan(0);
    }
  });
});
