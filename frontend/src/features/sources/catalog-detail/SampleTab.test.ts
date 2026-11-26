/** @vitest-environment jsdom */

import { MantineProvider } from "@mantine/core";
import { cleanup, fireEvent, render, screen, within } from "@testing-library/react";
import { createElement, type ReactNode } from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { SampleTab } from "@/features/sources/catalog-detail/SampleTab";
import { runObjectSample } from "@/features/sources/api/sample";
import type { CatalogColumn, CatalogObject, SampleResult } from "@/features/sources/types";
import { copyText } from "@/lib/copy-text";
import en from "@/locales/en-US/common.json";
import zh from "@/locales/zh-CN/common.json";

const copy = en as Record<string, string>;
const chinese = zh as Record<string, string>;

const openNotification = vi.hoisted(() => vi.fn());

function translate(key: string, options?: Record<string, unknown>) {
  const template = copy[key] ?? key;
  if (!options) return template;
  return template.replace(/\{\{(\w+)\}\}/g, (_, name: string) => String(options[name] ?? ""));
}

vi.mock("@refinedev/core", () => ({
  useTranslate: () => translate,
  useNotification: () => ({ open: openNotification }),
  useCan: () => ({ data: { can: true }, isLoading: false }),
}));

vi.mock("@/features/sources/api/sample", () => ({
  runObjectSample: vi.fn(),
}));

vi.mock("@/lib/copy-text", () => ({
  copyText: vi.fn().mockResolvedValue(undefined),
}));

function column(name: string, present: boolean): CatalogColumn {
  return {
    id: `col-${name}`,
    locator_key: `public.orders.${name}`,
    name,
    data_type: "text",
    nullable: true,
    business_name: null,
    business_description: null,
    ordinal: 1,
    is_present: present,
  };
}

function catalogObject(columns: CatalogColumn[]): CatalogObject {
  const present = columns.find((item) => item.is_present);
  return {
    id: "obj-1",
    locator_key: "public.orders",
    source_id: "src-1",
    object_type: "table",
    schema_name: "public",
    name: "orders",
    comment: null,
    primary_key: present ? [present.name] : [],
    business_name: "Orders",
    business_description: null,
    columns,
    foreign_keys: [],
    indexes: [],
    ddl: null,
    is_present: true,
    collected_at: null,
  };
}

function sampleResult(offset: number, truncated = false): SampleResult {
  return {
    columns: ["region"],
    declarations: [],
    rows: [["north"]],
    truncated,
    duration_ms: 12,
    offset,
    limit: 50,
    has_more: true,
  };
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
  Element.prototype.scrollIntoView = vi.fn();
}

function shell(node: ReactNode) {
  return createElement(MantineProvider, { env: "test" }, node);
}

function badgeRoot(label: string): HTMLElement {
  const root = screen.getByText(label).parentElement;
  if (!root) throw new Error("missing badge");
  return root;
}

function resultHeader(rowCount: string): HTMLElement {
  const header = screen.getByText(rowCount).parentElement;
  if (!header) throw new Error("missing result header");
  return header;
}

function chooseOption(label: string, optionName: string, index = 0) {
  const comboboxes = screen.getAllByRole("combobox", { name: label });
  const combobox = comboboxes[index];
  if (!combobox) throw new Error(`missing combobox ${label} at ${index}`);
  fireEvent.mouseDown(combobox);
  fireEvent.click(combobox);
  const controlsId = combobox.getAttribute("aria-controls");
  const controlled = controlsId ? document.getElementById(controlsId) : null;
  if (controlled) {
    fireEvent.click(
      within(controlled).getByRole("option", { name: optionName, hidden: true }),
    );
    return;
  }
  const lists = screen.getAllByRole("listbox", { hidden: true });
  const list = lists.find((item) =>
    within(item).queryByRole("option", { name: optionName, hidden: true }),
  );
  if (!list) throw new Error(`no listbox for ${optionName}`);
  fireEvent.click(within(list).getByRole("option", { name: optionName, hidden: true }));
}

async function loadSample(object: CatalogObject) {
  vi.mocked(runObjectSample).mockImplementation(async (_id, body) =>
    sampleResult(body.offset ?? 0, true),
  );
  render(shell(createElement(SampleTab, { object })));
  fireEvent.click(screen.getByRole("button", { name: copy["catalog.sample.load"] }));
  expect(await screen.findByText("north")).toBeTruthy();
}

describe("SampleTab result header", () => {
  beforeEach(() => {
    stubDomApis();
    vi.mocked(runObjectSample).mockReset();
    vi.mocked(copyText).mockClear();
    openNotification.mockReset();
  });

  afterEach(() => {
    cleanup();
  });

  it("shows an unstable-order badge on the result header when a later page has no order", async () => {
    expect(copy["catalog.sample.unstableOrder.badge"]).toBe("Unstable order");
    expect(chinese["catalog.sample.unstableOrder.badge"]).toBe(
      "\u987a\u5e8f\u4e0d\u7a33\u5b9a",
    );

    await loadSample(catalogObject([column("id", false)]));
    const header = resultHeader(translate("catalog.sample.rowCount", { count: 1 }));
    expect(header.textContent).not.toContain("Unstable order");
    expect(screen.queryByRole("alert")).toBeNull();

    fireEvent.click(screen.getByRole("button", { name: copy["catalog.sample.nextPage"] }));

    expect(await screen.findByText("Unstable order")).toBeTruthy();
    const settled = resultHeader(translate("catalog.sample.rowCount", { count: 1 }));
    expect(settled.textContent).toContain("Unstable order");
    expect(screen.getByText("north")).toBeTruthy();
    expect(screen.getByRole("button", { name: copy["catalog.sample.reload"] })).toBeTruthy();
    expect(screen.queryByRole("alert")).toBeNull();
    expect(screen.queryByText(copy["catalog.sample.unstableOrder"])).toBeNull();

    fireEvent.mouseEnter(badgeRoot("Unstable order"));
    expect(screen.getByRole("tooltip").textContent).toBe(copy["catalog.sample.unstableOrder"]);
    expect(screen.queryByRole("alert")).toBeNull();
  });

  it("shows an outdated badge on the result header when parameters no longer match", async () => {
    expect(copy["catalog.sample.outdated"]).toBe("Outdated");
    expect(chinese["catalog.sample.outdated"]).toBe("\u5df2\u8fc7\u671f");

    await loadSample(catalogObject([column("id", true)]));
    chooseOption(copy["catalog.sample.orderDirection"], copy["catalog.sample.orderDesc"]);

    expect(await screen.findByText("Outdated")).toBeTruthy();
    const header = resultHeader(translate("catalog.sample.rowCount", { count: 1 }));
    expect(header.textContent).toContain("Outdated");
    expect(header.textContent).not.toContain("Unstable order");
    expect(screen.getByText("north")).toBeTruthy();
    expect(screen.getByRole("button", { name: copy["catalog.sample.reload"] })).toBeTruthy();
    expect(screen.queryByRole("alert")).toBeNull();
    expect(screen.queryByText(copy["catalog.sample.stale"])).toBeNull();

    fireEvent.mouseEnter(badgeRoot("Outdated"));
    expect(screen.getByRole("tooltip").textContent).toBe(copy["catalog.sample.stale"]);
    expect(screen.queryByRole("alert")).toBeNull();
  });

  it("keeps the truncated badge and reload label when the sample is current", async () => {
    await loadSample(catalogObject([column("id", true)]));

    const header = resultHeader(translate("catalog.sample.rowCount", { count: 1 }));
    expect(header.textContent).toContain(copy["catalog.sample.truncated"]);
    expect(header.textContent).not.toContain("Unstable order");
    expect(header.textContent).not.toContain("Outdated");
    expect(screen.queryByText("Unstable order")).toBeNull();
    expect(screen.queryByText("Outdated")).toBeNull();
    expect(screen.getByText("north")).toBeTruthy();
    expect(screen.getByRole("button", { name: copy["catalog.sample.reload"] })).toBeTruthy();
    expect(screen.queryByText(copy["catalog.sample.unstableOrder"])).toBeNull();
    expect(screen.queryByText(copy["catalog.sample.stale"])).toBeNull();
    expect(screen.queryByRole("alert")).toBeNull();
  });

  it("supports multi-filter rows including is_null", async () => {
    vi.mocked(runObjectSample).mockResolvedValue(sampleResult(0, false));
    const object = catalogObject([column("id", true), column("region", true)]);
    render(shell(createElement(SampleTab, { object })));

    chooseOption(copy["catalog.sample.filterColumn"], "region", 0);
    chooseOption(copy["catalog.sample.filterOp"], copy["catalog.sample.opIsNull"], 0);

    fireEvent.click(screen.getByRole("button", { name: copy["catalog.sample.addFilter"] }));
    chooseOption(copy["catalog.sample.filterColumn"], "id", 1);
    const valueInputs = screen.getAllByRole("textbox", {
      name: copy["catalog.sample.filterValue"],
    });
    expect(valueInputs).toHaveLength(1);
    fireEvent.change(valueInputs[0]!, { target: { value: "42" } });

    fireEvent.click(screen.getByRole("button", { name: copy["catalog.sample.load"] }));
    expect(await screen.findByText("north")).toBeTruthy();

    expect(runObjectSample).toHaveBeenCalledWith(
      "obj-1",
      expect.objectContaining({
        filters: [
          { column: "region", op: "is_null", value: "" },
          { column: "id", op: "eq", value: "42" },
        ],
      }),
    );

    const removeButtons = screen.getAllByRole("button", {
      name: copy["catalog.sample.removeFilter"],
    });
    fireEvent.click(removeButtons[0]!);
    expect(
      screen.getAllByRole("combobox", { name: copy["catalog.sample.filterColumn"] }),
    ).toHaveLength(1);
  });

  it("supports column projection presets and compiled SQL preview", async () => {
    vi.mocked(runObjectSample).mockResolvedValue({
      columns: ["id"],
      declarations: [],
      rows: [["1"]],
      truncated: false,
      duration_ms: 8,
      offset: 0,
      limit: 50,
      has_more: false,
      sql: 'SELECT "id" FROM "public"."orders" ORDER BY "id" ASC LIMIT 50',
    });

    const object = catalogObject([column("id", true), column("region", true)]);
    render(shell(createElement(SampleTab, { object })));

    fireEvent.click(
      screen.getByRole("button", { name: copy["catalog.sample.columnsPkOnly"] }),
    );
    expect(
      screen.getByRole("button", { name: copy["catalog.sample.columnsReset"] }),
    ).toBeTruthy();

    fireEvent.click(screen.getByRole("switch", { name: copy["catalog.sample.showSql"] }));
    fireEvent.click(screen.getByRole("button", { name: copy["catalog.sample.load"] }));

    expect(
      await screen.findByText(
        'SELECT "id" FROM "public"."orders" ORDER BY "id" ASC LIMIT 50',
      ),
    ).toBeTruthy();

    expect(runObjectSample).toHaveBeenCalledWith(
      "obj-1",
      expect.objectContaining({
        columns: ["id"],
        include_sql: true,
      }),
    );

    fireEvent.click(screen.getByRole("button", { name: copy["catalog.sample.copySql"] }));
    expect(copyText).toHaveBeenCalledWith(
      'SELECT "id" FROM "public"."orders" ORDER BY "id" ASC LIMIT 50',
    );
  });

  it("supports header sorting and renders typed cells and precision warnings", async () => {
    vi.mocked(runObjectSample).mockResolvedValue({
      columns: ["id", "note", "active", "payload", "seen_at"],
      declarations: [
        {
          name: "seen_at",
          temporal_kind: "time",
          precision: 3,
          nullable: true,
        },
      ],
      rows: [[null, "", true, { encoding: "base64", data: "AQID" }, "01:02:03.1234"]],
      truncated: false,
      duration_ms: 5,
      offset: 0,
      limit: 50,
      has_more: false,
    });

    const object = catalogObject([
      column("id", true),
      column("note", true),
      column("active", true),
      column("payload", true),
      column("seen_at", true),
    ]);
    render(shell(createElement(SampleTab, { object })));

    fireEvent.click(screen.getByRole("button", { name: copy["catalog.sample.load"] }));

    expect(await screen.findByText(copy["catalog.sample.nullBadge"])).toBeTruthy();
    expect(screen.getByText(copy["catalog.sample.emptyStringBadge"])).toBeTruthy();
    expect(screen.getByText("true")).toBeTruthy();
    expect(
      screen.getByText(translate("catalog.sample.binaryBadge", { bytes: 3 })),
    ).toBeTruthy();
    expect(screen.getByLabelText(copy["catalog.sample.precision"])).toBeTruthy();

    fireEvent.click(
      screen.getByRole("button", {
        name: translate("catalog.sample.sortBy", { column: "note" }),
      }),
    );
    expect(await screen.findByText("Outdated")).toBeTruthy();
  });

  it("opens the row inspector drawer and copies row JSON and cell values", async () => {
    vi.mocked(runObjectSample).mockResolvedValue({
      columns: ["id", "region"],
      declarations: [],
      rows: [[101, "west"]],
      truncated: false,
      duration_ms: 7,
      offset: 0,
      limit: 50,
      has_more: false,
    });

    const object = catalogObject([column("id", true), column("region", true)]);
    render(shell(createElement(SampleTab, { object })));

    fireEvent.click(screen.getByRole("button", { name: copy["catalog.sample.load"] }));
    expect(await screen.findByText("west")).toBeTruthy();

    fireEvent.click(
      screen.getByRole("button", {
        name: translate("catalog.sample.inspectRow", { index: 1 }),
      }),
    );

    expect(
      await screen.findByText(translate("catalog.sample.rowDrawerTitle", { index: 1 })),
    ).toBeTruthy();

    fireEvent.click(
      screen.getByRole("button", { name: copy["catalog.sample.copyRowJson"] }),
    );
    expect(copyText).toHaveBeenCalledWith(
      JSON.stringify({ id: 101, region: "west" }, null, 2),
    );

    const copyCellButtons = screen.getAllByRole("button", {
      name: copy["catalog.sample.copyCell"],
    });
    fireEvent.click(copyCellButtons[1]!);
    expect(copyText).toHaveBeenCalledWith("west");
  });
});
