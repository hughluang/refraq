/** @vitest-environment jsdom */

import { MantineProvider } from "@mantine/core";
import { cleanup, fireEvent, render, screen, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { useState } from "react";

import type { DataSchema } from "./accessTypes";
import { EntityDataQueryControls } from "./EntityDataQueryControls";
import { EMPTY_DATA_QUERY, type EntityDataQuery } from "./entityDataQuery";
import en from "@/locales/en-US/common.json";

vi.mock("@refinedev/core", () => ({
  useTranslate: () => (key: string, args?: Record<string, string>) => {
    const template = en[key as keyof typeof en] ?? key;
    return template.replace(/\{\{(\w+)\}\}/g, (_, name: string) => args?.[name] ?? name);
  },
}));
const schema: DataSchema = {
  entity: { table_name: "part", name: "Part", writable: false },
  withheld_field: null,
  business_key: "code",
  row_id: { type: "integer", operators: ["eq"] },
  attributes: [
    { name: "code", type: "string", operators: ["eq", "contains"] },
    {
      name: "state",
      type: "dictionary",
      operators: ["eq"],
      codes: [{ code: "old", label: "Retired", writable: false }],
    },
    { name: "due", type: "date", operators: ["eq", "gte", "lte"] },
  ],
};
function mount(initial = EMPTY_DATA_QUERY) {
  const submit = vi.fn();
  const change = vi.fn();
  function Browser() {
    const [query, setQuery] = useState(initial);
    return (
      <MantineProvider env="test">
        <form
          onSubmit={(e) => {
            e.preventDefault();
            submit();
          }}
        >
          <EntityDataQueryControls
            schema={schema}
            query={query}
            onChange={(next) => {
              setQuery(next);
              change(next);
            }}
          />
        </form>
      </MantineProvider>
    );
  }
  render(<Browser />);
  return { submit, change };
}
function choose(label: string, name: string) {
  const combo = screen.getByRole("combobox", { name: label });
  fireEvent.mouseDown(combo);
  const option = screen
    .getAllByRole("listbox", { hidden: true })
    .flatMap((list) => within(list).queryAllByRole("option", { name, hidden: true }))[0];
  expect(option).toBeDefined();
  fireEvent.click(option);
}
beforeEach(() => {
  Object.defineProperty(window, "matchMedia", {
    writable: true,
    value: () => ({
      matches: false,
      addEventListener() {},
      removeEventListener() {},
    }),
  });
  globalThis.ResizeObserver = class {
    observe() {}
    unobserve() {}
    disconnect() {}
  };
});
afterEach(cleanup);

describe("entity data query controls", () => {
  it("submits a lookup on Enter and clears an applied lookup without removing conditions", () => {
    const query: EntityDataQuery = {
      ...EMPTY_DATA_QUERY,
      conditions: [{ field: "due", op: "eq", values: ["2026-11-24"] }],
    };
    const { submit, change } = mount(query);
    const input = screen.getByRole("textbox", { name: "Exact code" });
    fireEvent.change(input, { target: { value: " ABC " } });
    expect(fireEvent.keyDown(input, { key: "Enter" })).toBe(false);
    expect(change).toHaveBeenLastCalledWith({
      ...query,
      lookup: { field: "code", value: " ABC " },
    });
    fireEvent.change(input, { target: { value: "" } });
    expect(change).toHaveBeenLastCalledWith(query);
    expect(submit).not.toHaveBeenCalled();
  });

  it("selects a published dictionary code or date directly from quick lookup", () => {
    const { change } = mount();
    choose("Search column", "state");
    choose("Exact state", "Retired (old)");
    fireEvent.click(screen.getByRole("button", { name: "Search" }));
    expect(change.mock.lastCall?.[0].lookup).toEqual({ field: "state", value: "old" });
    choose("Search column", "due");
    const date = screen.getByLabelText("Exact due") as HTMLInputElement;
    expect(date.type).toEqual("date");
    fireEvent.change(date, { target: { value: "2026-11-24" } });
    fireEvent.click(screen.getByRole("button", { name: "Search" }));
    expect(change.mock.lastCall?.[0].lookup).toEqual({ field: "due", value: "2026-11-24" });
  });

  it("edits an existing filter chip and applies the group matching mode", () => {
    const query: EntityDataQuery = {
      ...EMPTY_DATA_QUERY,
      conditions: [
        { field: "state", op: "eq", values: ["old"] },
        { field: "code", op: "contains", values: ["old"] },
      ],
    };
    const { submit, change } = mount(query);
    fireEvent.click(screen.getByRole("button", { name: "code contains old" }));
    choose("Match", "Match any");
    const value = screen.getByLabelText("Value");
    fireEvent.change(value, { target: { value: "new" } });
    expect(fireEvent.keyDown(value, { key: "Enter" })).toBe(false);
    expect(change).toHaveBeenLastCalledWith({
      ...query,
      match: "any",
      conditions: [query.conditions[0], { field: "code", op: "contains", values: ["new"] }],
    });
    expect(submit).not.toHaveBeenCalled();
  });
});
