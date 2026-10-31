/** @vitest-environment jsdom */

import { MantineProvider } from "@mantine/core";
import { notifications, notificationsStore } from "@mantine/notifications";
import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { createElement, type ReactNode } from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { ConsoleNotifications } from "@/providers/notification-provider";

import { listAccountGroups } from "@/features/account/api";
import { loadDataSchema, queryDataRows } from "@/features/entities/accessApi";
import { EntityDataBrowser } from "@/features/entities/EntityDataBrowser";
import type { DataSchema } from "@/features/entities/accessTypes";
import { ApiError } from "@/lib/api";

const session = vi.hoisted(() => ({
  role_id: "role_operator" as string | null,
  role_name: "Operator" as string | null,
}));

vi.mock("@refinedev/core", () => ({
  useTranslate: () => (key: string) => key,
  useGetIdentity: () => ({
    data: {
      id: "user_1",
      account: "ada",
      display_name: "Ada",
      email: null,
      locale: "zh-CN",
      display_timezone: null,
      role_id: session.role_id,
      role_key: "operator",
      role_name: session.role_name,
      permissions: ["entity:data_read"],
      identity_source: "local" as const,
    },
  }),
}));

vi.mock("@/features/entities/accessApi", () => ({
  loadDataSchema: vi.fn(),
  queryDataRows: vi.fn(),
}));

vi.mock("@/features/account/api", () => ({
  listAccountGroups: vi.fn(),
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

const schema: DataSchema = {
  entity: { table_name: "material", writable: true, name: "Material" },
  attributes: [{ name: "sku", type: "string" }],
  withheld_field: null,
  business_key: "sku",
};

function resetNotifications() {
  const state = notificationsStore.getState();
  for (const item of [...state.notifications, ...state.queue]) {
    notifications.hide(item.id);
  }
  notifications.clean();
}

function renderBrowser(active = true, physicalHidden = false) {
  return render(
    createElement(
      MantineProvider,
      { env: "test" },
      createElement(ConsoleNotifications),
      createElement(EntityDataBrowser, {
        tableName: "material",
        physicalHidden,
        active,
      }),
    ) as ReactNode,
  );
}

function paintedStyle(node: HTMLElement): string {
  let current: HTMLElement | null = node;
  while (current) {
    const style = current.getAttribute("style") ?? "";
    if (style.includes("--alert-") || style.includes("--refraq-tone-")) return style;
    current = current.parentElement;
  }
  return "";
}

function chooseView(optionName: string) {
  const combobox = screen.getByRole("combobox", { name: "entities.data.narrow" });
  fireEvent.mouseDown(combobox);
  const lists = screen.getAllByRole("listbox", { hidden: true });
  const list = lists.find((item) =>
    within(item).queryByRole("option", { name: optionName, hidden: true }),
  );
  if (!list) throw new Error(`no listbox for ${optionName}`);
  fireEvent.click(within(list).getByRole("option", { name: optionName, hidden: true }));
}

function refreshButton() {
  return screen.getByRole("button", { name: "entities.data.refresh" }) as HTMLButtonElement;
}

describe("EntityDataBrowser", () => {
  beforeEach(() => {
    stubDomApis();
    resetNotifications();
    session.role_id = "role_operator";
    session.role_name = "Operator";
    vi.mocked(loadDataSchema).mockResolvedValue(schema);
    vi.mocked(queryDataRows).mockResolvedValue({
      items: [{ row_id: 1, sku: "ABC" }],
      total: 1,
      limit: 50,
      offset: 0,
    });
    vi.mocked(listAccountGroups).mockResolvedValue({ groups: [] });
  });

  afterEach(() => {
    cleanup();
    resetNotifications();
    vi.clearAllMocks();
  });

  it("explains hidden physical columns in an info callout", async () => {
    renderBrowser(true, true);

    const copy = await screen.findByText("entities.data.physicalHidden");
    expect(copy.closest("[role='alert']")).toBeNull();
    expect(copy.closest("[role='group']")).toBeTruthy();
    expect(paintedStyle(copy)).toContain("var(--refraq-tone-info)");
    expect(paintedStyle(copy)).not.toMatch(/red/i);
    expect(copy.closest("[role='group']")?.querySelector("button")).toBeNull();
  });

  it("shows a dynamic time cell as the response string", async () => {
    const seenAt = "2024-01-02T01:02:03.123456+08:00";
    vi.mocked(loadDataSchema).mockResolvedValue({
      ...schema,
      attributes: [{ name: "seen_at", type: "string" }],
    });
    vi.mocked(queryDataRows).mockResolvedValue({
      items: [{ row_id: 1, seen_at: seenAt }],
      total: 1,
      limit: 50,
      offset: 0,
    });
    renderBrowser();

    expect(await screen.findByText(seenAt)).toBeTruthy();
    expect(queryDataRows).toHaveBeenCalledWith("material", { limit: 50, offset: 0 });
  });

  it("loads the full view when the tab is visible", async () => {
    renderBrowser();

    expect(screen.queryByText("entities.tabs.data")).toBeNull();
    expect(screen.queryByText("entities.data.narrowHint")).toBeNull();
    expect(await screen.findByText("ABC")).toBeTruthy();
    expect(loadDataSchema).toHaveBeenCalledWith("material", {});
    expect(queryDataRows).toHaveBeenCalledWith("material", { limit: 50, offset: 0 });
    expect(screen.getByText("common.showing")).toBeTruthy();
  });

  it("does not query while the data tab is hidden", () => {
    renderBrowser(false);

    expect(loadDataSchema).not.toHaveBeenCalled();
    expect(queryDataRows).not.toHaveBeenCalled();
  });

  it("narrows to the session role without listing roles", async () => {
    renderBrowser();
    await screen.findByText("ABC");
    chooseView("entities.data.narrow.role");

    expect(screen.getByText("entities.data.narrowHint")).toBeTruthy();
    await waitFor(() => {
      expect(loadDataSchema).toHaveBeenCalledWith("material", {
        narrow: { type: "role", id: "role_operator" },
      });
    });
    expect(queryDataRows).toHaveBeenCalledWith("material", {
      limit: 50,
      offset: 0,
      narrow: { type: "role", id: "role_operator" },
    });
    expect(listAccountGroups).not.toHaveBeenCalled();
  });

  it("omits the role choice when the session has no role", async () => {
    session.role_id = null;
    renderBrowser();
    await screen.findByText("ABC");
    const combobox = screen.getByRole("combobox", { name: "entities.data.narrow" });
    fireEvent.mouseDown(combobox);
    const lists = screen.getAllByRole("listbox", { hidden: true });
    expect(
      lists.some((item) =>
        within(item).queryByRole("option", { name: "entities.data.narrow.role", hidden: true }),
      ),
    ).toBe(false);
  });

  it("loads a group only after one of the caller's groups is chosen", async () => {
    vi.mocked(listAccountGroups).mockResolvedValue({
      groups: [{ id: "grp_east", key: "east", name: "East" }],
    });
    renderBrowser();
    await screen.findByText("ABC");
    chooseView("entities.data.narrow.group");

    expect(refreshButton().disabled).toBe(true);
    expect(loadDataSchema).toHaveBeenCalledTimes(1);
    expect(loadDataSchema).not.toHaveBeenCalledWith("material", {
      narrow: { type: "group", id: "grp_east" },
    });

    await waitFor(() => {
      expect(
        (screen.getByRole("combobox", { name: "entities.data.group" }) as HTMLButtonElement)
          .disabled,
      ).toBe(false);
    });
    const groupBox = screen.getByRole("combobox", { name: "entities.data.group" });
    fireEvent.mouseDown(groupBox);
    const lists = screen.getAllByRole("listbox", { hidden: true });
    const list = lists.find((item) =>
      within(item).queryByRole("option", { name: "East", hidden: true }),
    );
    if (!list) throw new Error("group option missing");
    fireEvent.click(within(list).getByRole("option", { name: "East", hidden: true }));

    await waitFor(() => {
      expect(loadDataSchema).toHaveBeenCalledWith("material", {
        narrow: { type: "group", id: "grp_east" },
      });
    });
    expect(listAccountGroups).toHaveBeenCalledOnce();
    expect(queryDataRows).toHaveBeenCalledWith("material", {
      limit: 50,
      offset: 0,
      narrow: { type: "group", id: "grp_east" },
    });
  });

  it("notifies a group-list failure without marking the data table unloaded", async () => {
    vi.mocked(listAccountGroups).mockRejectedValue(
      new ApiError(500, "NO_SUCH_CODE", "groups offline", "req-groups"),
    );
    renderBrowser();
    await screen.findByText("ABC");
    const schemaCalls = vi.mocked(loadDataSchema).mock.calls.length;
    chooseView("entities.data.narrow.group");

    const notice = await screen.findByRole("alert");
    expect(notice.textContent).toContain("problems.unknown");
    expect(screen.queryByRole("button", { name: "status.unloaded" })).toBeNull();
    expect(screen.queryByRole("table")).toBeNull();
    expect(loadDataSchema).toHaveBeenCalledTimes(schemaCalls);
    expect(queryDataRows).toHaveBeenCalledTimes(1);

    fireEvent.click(screen.getByText("form.error.details"));
    expect(screen.getByText("groups offline").closest("details")).toBeTruthy();
    expect(screen.getByText("common.requestId: req-groups").closest("details")).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "common.retry" }));
    await waitFor(() => expect(listAccountGroups).toHaveBeenCalledTimes(2));
    expect(loadDataSchema).toHaveBeenCalledTimes(schemaCalls);
    expect(queryDataRows).toHaveBeenCalledTimes(1);
  });

  it("does not query when the caller has no groups", async () => {
    renderBrowser();
    await screen.findByText("ABC");
    chooseView("entities.data.narrow.group");

    expect(await screen.findByText("entities.data.noGroups")).toBeTruthy();
    expect(refreshButton().disabled).toBe(true);
    expect(loadDataSchema).toHaveBeenCalledTimes(1);
    expect(loadDataSchema).toHaveBeenCalledWith("material", {});
  });

  it("shows the no-grant copy instead of the entity-not-found detail", async () => {
    vi.mocked(loadDataSchema).mockRejectedValue(
      new ApiError(
        404,
        "ENTITY_NOT_FOUND",
        "Business Entity with table_name 'material' was not found",
        "req-grant",
      ),
    );
    renderBrowser();

    expect(await screen.findByRole("button", { name: "status.unloaded" })).toBeTruthy();
    expect(await screen.findAllByRole("alert")).toHaveLength(1);
    const notice = screen.getByRole("alert");
    expect(notice.textContent).toContain("entities.data.noGrant");
    expect(screen.getByRole("table").querySelector("[role='alert']")).toBeNull();
    expect(
      screen.queryByText("Business Entity with table_name 'material' was not found"),
    ).toBeNull();
    fireEvent.click(screen.getByText("form.error.details"));
    expect(screen.getByText("common.requestId: req-grant").closest("details")).toBeTruthy();
    expect(screen.queryByText("status.unloaded")?.closest("[role='alert']")).toBeNull();

    fireEvent.click(screen.getByRole("button", { name: "common.retry" }));
    await waitFor(() => {
      expect(loadDataSchema).toHaveBeenCalledTimes(2);
    });
  });

  it("shows the narrow-rejected copy for an identity the caller does not hold", async () => {
    vi.mocked(loadDataSchema).mockRejectedValue(
      new ApiError(422, "ENTITY_ACCESS_INVALID", "narrow group is not an identity of the subject"),
    );
    renderBrowser();

    expect(await screen.findByRole("button", { name: "status.unloaded" })).toBeTruthy();
    expect(await screen.findAllByRole("alert")).toHaveLength(1);
    expect(screen.getByRole("alert").textContent).toContain("entities.data.narrowRejected");
    expect(screen.getByRole("table").querySelector("[role='alert']")).toBeNull();
    expect(screen.queryByText("narrow group is not an identity of the subject")).toBeNull();
  });

  it("shows an empty status row under the columns", async () => {
    vi.mocked(queryDataRows).mockResolvedValue({
      items: [],
      total: 0,
      limit: 50,
      offset: 0,
    });
    renderBrowser();

    expect(await screen.findByText("entities.data.empty")).toBeTruthy();
    const table = screen.getByRole("table");
    expect(within(table).getByText("entities.data.empty")).toBeTruthy();
    expect(within(table).getByRole("columnheader", { name: "sku" })).toBeTruthy();
    expect(screen.getByText("common.showing")).toBeTruthy();
  });

  it("offers full access again when a narrowed view has no rows", async () => {
    vi.mocked(queryDataRows).mockResolvedValue({
      items: [],
      total: 0,
      limit: 50,
      offset: 0,
    });
    renderBrowser();
    await screen.findByText("entities.data.empty");
    chooseView("entities.data.narrow.user");

    expect(await screen.findByText("entities.data.emptyNarrowed")).toBeTruthy();
    expect(screen.queryByText("entities.data.empty")).toBeNull();
    fireEvent.click(screen.getByRole("button", { name: "entities.data.useFullAccess" }));

    await waitFor(() => {
      expect(loadDataSchema).toHaveBeenLastCalledWith("material", {});
    });
    expect(await screen.findByText("entities.data.empty")).toBeTruthy();
  });

  it("requests the next page when more than 50 rows exist", async () => {
    vi.mocked(queryDataRows).mockResolvedValue({
      items: [{ row_id: 1, sku: "ABC" }],
      total: 80,
      limit: 50,
      offset: 0,
    });
    renderBrowser();
    await screen.findByText("ABC");

    fireEvent.click(screen.getByRole("button", { name: "2" }));

    await waitFor(() => {
      expect(queryDataRows).toHaveBeenCalledWith("material", { limit: 50, offset: 50 });
    });
  });

  it("keeps the rows and sends one error notification when a later refresh fails", async () => {
    renderBrowser();
    expect(await screen.findByText("ABC")).toBeTruthy();

    vi.mocked(queryDataRows).mockRejectedValue(
      new ApiError(500, "NO_SUCH_CODE", "upstream timed out", "req-later"),
    );
    fireEvent.click(refreshButton());

    expect(await screen.findAllByRole("alert")).toHaveLength(1);
    const notice = screen.getByRole("alert");
    expect(notice.textContent).toContain("problems.unknown");
    expect(screen.getByText("ABC")).toBeTruthy();
    expect(screen.getByRole("table").querySelector("[role='alert']")).toBeNull();
    expect(screen.queryByRole("button", { name: "status.unloaded" })).toBeNull();
    fireEvent.click(screen.getByText("form.error.details"));
    expect(screen.getByText("upstream timed out").closest("details")).toBeTruthy();
    expect(screen.getByText("common.requestId: req-later").closest("details")).toBeTruthy();
  });

  it("reports access pending as an error notification and keeps the rows", async () => {
    renderBrowser();
    expect(await screen.findByText("ABC")).toBeTruthy();

    vi.mocked(loadDataSchema).mockRejectedValue(
      new ApiError(503, "ENTITY_ACCESS_PENDING", "views are generating", "req-pending"),
    );
    fireEvent.click(refreshButton());

    expect(await screen.findAllByRole("alert")).toHaveLength(1);
    const notice = screen.getByRole("alert");
    expect(notice.textContent).toContain("entities.data.pending");
    expect(notice.textContent).not.toContain("views are generating");
    expect(screen.getByText("ABC")).toBeTruthy();
    expect(screen.getByRole("table").querySelector("[role='alert']")).toBeNull();
    expect(screen.queryByText("status.unloaded")).toBeNull();
  });

  it("ignores a slow response from the previous identity", async () => {
    let releaseFirst: (value: DataSchema) => void = () => {};
    vi.mocked(loadDataSchema).mockImplementationOnce(
      () =>
        new Promise((resolve) => {
          releaseFirst = resolve;
        }),
    );
    vi.mocked(queryDataRows).mockImplementation(async (_table, body) => ({
      items: [{ row_id: 1, sku: "narrow" in body ? "NARROW" : "FULL" }],
      total: 1,
      limit: 50,
      offset: 0,
    }));
    renderBrowser();
    chooseView("entities.data.narrow.user");
    expect(await screen.findByText("NARROW")).toBeTruthy();

    releaseFirst(schema);
    await waitFor(() => {
      expect(screen.queryByText("FULL")).toBeNull();
    });
    expect(screen.getByText("NARROW")).toBeTruthy();
  });
});
