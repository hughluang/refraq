/** @vitest-environment jsdom */

import { MantineProvider } from "@mantine/core";
import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { createElement, type ReactNode } from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

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

function renderBrowser(active = true) {
  return render(
    createElement(
      MantineProvider,
      null,
      createElement(EntityDataBrowser, {
        tableName: "material",
        physicalHidden: false,
        active,
      }),
    ) as ReactNode,
  );
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
    vi.clearAllMocks();
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
      ),
    );
    renderBrowser();

    expect(await screen.findByText("entities.data.noGrant")).toBeTruthy();
    expect(
      screen.queryByText("Business Entity with table_name 'material' was not found"),
    ).toBeNull();
  });

  it("shows the narrow-rejected copy for an identity the caller does not hold", async () => {
    vi.mocked(loadDataSchema).mockRejectedValue(
      new ApiError(422, "ENTITY_ACCESS_INVALID", "narrow group is not an identity of the subject"),
    );
    renderBrowser();

    expect(await screen.findByText("entities.data.narrowRejected")).toBeTruthy();
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
