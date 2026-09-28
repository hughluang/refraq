/** @vitest-environment jsdom */

import { MantineProvider } from "@mantine/core";
import { useForm } from "@mantine/form";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { createElement, type ReactNode } from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { listEntities } from "@/features/entities/api";
import { AttributeEditor } from "@/features/entities/AttributeEditor";
import { EMPTY_ATTRIBUTE } from "@/features/entities/constants";
import type {
  AttributeDraft,
  EntityRecordFormValues,
} from "@/features/entities/types";

vi.mock("@refinedev/core", () => ({
  useTranslate: () => (key: string, values?: Record<string, unknown>) => {
    if (!values) return key;
    if ("count" in values) return `${key}:${String(values.count)}`;
    if ("value" in values) return `${key}:${String(values.value)}`;
    if ("precision" in values && "scale" in values) {
      return `${key}:${String(values.precision)},${String(values.scale)}`;
    }
    return key;
  },
}));

vi.mock("@/features/entities/api", () => ({
  listEntities: vi.fn(async () => ({
    items: [],
    total: 0,
    limit: 50,
    offset: 0,
  })),
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

function draft(overrides: Partial<AttributeDraft> = {}): AttributeDraft {
  return { ...EMPTY_ATTRIBUTE, ...overrides };
}

function Host({
  editable,
  attributes,
}: {
  editable: boolean;
  attributes: AttributeDraft[];
}) {
  const form = useForm<EntityRecordFormValues>({
    initialValues: {
      table_name: "items",
      name: "Items",
      description: "Items",
      attributes,
    },
  });
  return createElement(AttributeEditor, {
    form,
    editable,
    selfEntityId: null,
  });
}

function renderEditor(editable: boolean, attributes: AttributeDraft[]) {
  return render(
    createElement(
      MantineProvider,
      { env: "test" },
      createElement(Host, { editable, attributes }) as ReactNode,
    ),
  );
}

describe("AttributeEditor", () => {
  beforeEach(() => {
    stubDomApis();
  });

  afterEach(() => {
    cleanup();
  });

  it("shows the database column type in the table and the drawer", () => {
    renderEditor(true, [
      draft({ name: "sku", max_length: "32" }),
      draft({ name: "qty", type: "number", max_length: "" }),
    ]);

    expect(screen.getByText("VARCHAR(32)")).toBeTruthy();
    expect(screen.getByText("DOUBLE PRECISION")).toBeTruthy();

    fireEvent.click(screen.getByText("sku"));
    expect(screen.getByText("entities.fields.databaseType")).toBeTruthy();
    expect(screen.getAllByText("VARCHAR(32)")).toHaveLength(2);
  });

  it("shows type configuration and keeps type config out of the table", () => {
    renderEditor(true, [
      draft({ name: "sku", max_length: "32" }),
      draft({
        name: "price",
        type: "decimal",
        precision: "10",
        scale: "2",
        max_length: "",
      }),
      draft({
        name: "status",
        type: "enumeration",
        enumeration_text: "A\nB\nC",
        max_length: "",
      }),
    ]);

    expect(screen.getByText("entities.fields.attributeConfig")).toBeTruthy();
    expect(screen.getByText("entities.attributes.config.maxLength:32")).toBeTruthy();
    expect(
      screen.getByText("entities.attributes.config.decimal:10,2"),
    ).toBeTruthy();
    expect(
      screen.getByText("entities.attributes.config.enumeration:3"),
    ).toBeTruthy();
    expect(
      screen.queryByRole("textbox", { name: "entities.fields.maxLength" }),
    ).toBeNull();
    expect(
      screen.queryByRole("textbox", { name: "entities.fields.enumeration" }),
    ).toBeNull();
    expect(
      screen.queryByRole("combobox", { name: "entities.fields.attributeType" }),
    ).toBeNull();
  });

  it("writes the draft only after confirm", () => {
    renderEditor(true, [draft({ name: "sku", max_length: "32" })]);

    fireEvent.click(screen.getByText("sku"));
    fireEvent.change(
      screen.getByRole("textbox", { name: "entities.fields.attributeName" }),
      { target: { value: "sku_code" } },
    );
    expect(screen.getByText("sku")).toBeTruthy();

    fireEvent.click(
      screen.getByRole("button", {
        name: "entities.attributes.drawer.confirm",
      }),
    );

    expect(screen.getByText("sku_code")).toBeTruthy();
    expect(
      screen.queryByRole("textbox", { name: "entities.fields.attributeName" }),
    ).toBeNull();
  });

  it("drops drawer edits on cancel and blocks confirm when length is missing", () => {
    renderEditor(true, [draft({ name: "sku", max_length: "" })]);

    fireEvent.click(screen.getByText("sku"));
    fireEvent.change(
      screen.getByRole("textbox", { name: "entities.fields.attributeName" }),
      { target: { value: "renamed" } },
    );
    fireEvent.click(
      screen.getByRole("button", {
        name: "entities.attributes.drawer.cancel",
      }),
    );
    expect(screen.getByText("sku")).toBeTruthy();
    expect(screen.queryByText("renamed")).toBeNull();

    fireEvent.click(screen.getByText("sku"));
    fireEvent.click(
      screen.getByRole("button", {
        name: "entities.attributes.drawer.confirm",
      }),
    );
    expect(
      screen.getByText("entities.validation.attribute.maxLengthRequired"),
    ).toBeTruthy();
    expect(
      screen.getByRole("textbox", { name: "entities.fields.attributeName" }),
    ).toBeTruthy();
    expect(screen.queryByText("renamed")).toBeNull();
  });

  it("shows a reference by name and does not keep a typed search as the target", () => {
    renderEditor(true, [
      draft({
        name: "supplier_id",
        type: "reference",
        target_entity_id: "ent_supplier",
        target_name: "Supplier",
        target_table_name: "supplier",
      }),
    ]);

    expect(screen.getByText("Supplier（supplier）")).toBeTruthy();
    fireEvent.click(screen.getByText("supplier_id"));
    const target = screen.getByRole("combobox", {
      name: "entities.fields.targetTableName",
    });
    fireEvent.change(target, { target: { value: "not-an-entity" } });
    fireEvent.click(
      screen.getByRole("button", {
        name: "entities.attributes.drawer.confirm",
      }),
    );
    expect(screen.getByText("Supplier（supplier）")).toBeTruthy();
    expect(screen.queryByText("not-an-entity")).toBeNull();
  });

  it("shows a target search failure instead of an empty result", async () => {
    vi.mocked(listEntities).mockRejectedValueOnce(new Error("down"));
    renderEditor(true, [
      draft({
        name: "supplier_id",
        type: "reference",
        target_entity_id: "ent_supplier",
        target_name: "Supplier",
        target_table_name: "supplier",
      }),
    ]);

    fireEvent.click(screen.getByText("supplier_id"));

    expect(
      await screen.findByText("entities.attributes.targetLoadFailed"),
    ).toBeTruthy();
    expect(
      screen.queryByText("entities.attributes.targetNothingFound"),
    ).toBeNull();
  });

  it("does not open the drawer in display mode", () => {
    renderEditor(false, [draft({ name: "sku", max_length: "32" })]);

    fireEvent.click(screen.getByText("sku"));
    expect(
      screen.queryByRole("textbox", { name: "entities.fields.attributeName" }),
    ).toBeNull();
    expect(
      screen.queryByRole("button", { name: "actions.delete" }),
    ).toBeNull();
    expect(
      screen.queryByRole("button", { name: "entities.attributes.add" }),
    ).toBeNull();
  });
});
