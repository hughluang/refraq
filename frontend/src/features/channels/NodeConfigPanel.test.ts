/** @vitest-environment jsdom */

import { MantineProvider } from "@mantine/core";
import { cleanup, render, screen, waitFor, within } from "@testing-library/react";
import { createElement, type ReactNode } from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import type { SchemaObject } from "@/features/channels/configSchemaForm";
import type { FlowNodeData } from "@/features/channels/graphValidation";
import { listEntities, listVersions } from "@/features/entities/api";
import type { EntityAttribute, EntityVersion } from "@/features/entities/types";

const LABELS: Record<string, string> = {
  "channels.node.name": "Name",
  "channels.node.ref": "Ref",
  "channels.node.close": "Close",
  "channels.node.onError": "On error",
  "channels.node.onError.stop": "Stop",
  "channels.config.addItem": "Add",
  "channels.config.removeItem": "Remove",
  "channels.config.businessKey": "Business Key",
  "channels.config.noAttributes": "No attributes",
  "channels.config.pickEntity": "Choose an Entity",
  "channels.config.attributeLoadFailed": "Could not load attributes",
  "channels.config.mapping.matchKeyMissing": "Mapping must include {{name}}",
  "channels.config.fields.entity_id": "Entity",
  "channels.config.fields.filters": "Filters",
  "channels.config.fields.attribute": "Attribute",
  "channels.config.fields.op": "Operator",
  "channels.config.fields.value": "Value",
  "channels.config.fields.mode": "Mode",
  "channels.config.fields.match_key": "Match key",
  "channels.config.fields.mapping": "Mapping",
  "channels.config.fields.source": "Source",
  "channels.config.fields.key": "Source key",
  "channels.config.fields.on_incompatible_head": "Incompatible head",
  "channels.config.options.mode.upsert": "Upsert",
  "channels.config.options.mode.delete": "Delete",
  "channels.config.options.op.eq": "Equals",
  "channels.config.options.on_incompatible_head.fail": "Fail",
};

vi.mock("@refinedev/core", () => ({
  useTranslate: () => (key: string, values?: Record<string, unknown>) => {
    const template = LABELS[key] ?? key;
    if (!values) return template;
    return template.replace(/\{\{(\w+)\}\}/g, (_, name: string) => String(values[name] ?? ""));
  },
}));

vi.mock("@/features/entities/api", () => ({
  listVersions: vi.fn(),
  getVersion: vi.fn(),
  listEntities: vi.fn(),
}));

const WRITE: SchemaObject = {
  type: "object",
  properties: {
    entity_id: { type: "string", "x-refraq-ref": "entity" },
    mode: { type: "string", enum: ["upsert", "delete"] },
    match_key: { type: ["string", "null"], "x-refraq-ref": "match_key" },
    source: { type: "string" },
    mapping: {
      type: "array",
      items: {
        type: "object",
        properties: {
          attribute: { type: "string", "x-refraq-ref": "entity_attribute" },
          key: { type: "string" },
        },
      },
    },
    on_incompatible_head: { type: "string", enum: ["fail"] },
  },
};

const READ: SchemaObject = {
  type: "object",
  properties: {
    entity_id: { type: "string", "x-refraq-ref": "entity" },
    filters: {
      type: "array",
      items: {
        type: "object",
        properties: {
          attribute: { type: "string", "x-refraq-ref": "entity_attribute" },
          op: { type: "string", enum: ["eq"] },
          value: { type: "string" },
        },
      },
    },
  },
};

function attribute(name: string, businessKey = false): EntityAttribute {
  return {
    name,
    type: "string",
    required: false,
    unique: businessKey,
    indexed: false,
    business_key: businessKey,
    description: null,
    config: {},
  };
}

function version(attributes: EntityAttribute[]): EntityVersion {
  return {
    id: "ver_1",
    entity_id: "ent_1",
    version: 1,
    publish_status: "published",
    attributes,
    table_name: "items",
    alignment: { table_present: true, latest_job_id: null, latest_job_status: null },
    created_at: "2026-01-01T00:00:00Z",
    updated_at: "2026-01-01T00:00:00Z",
  };
}

function node(config: Record<string, unknown>, nodeType = "write.entity"): FlowNodeData {
  return {
    nodeType,
    ref: "step",
    name: "Step",
    config,
    onError: "stop",
    retry: null,
    entry: false,
    problem: false,
    typeVersion: 1,
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
}

function renderPanel(schema: SchemaObject, data: FlowNodeData, onChange = vi.fn()) {
  return import("@/features/channels/NodeConfigPanel").then(({ NodeConfigPanel }) => {
    render(
      createElement(
        MantineProvider,
        null,
        createElement(NodeConfigPanel, {
          nodeId: "n1",
          data,
          spec: null,
          schema,
          editable: true,
          onClose: vi.fn(),
          onChange,
        }) as ReactNode,
      ),
    );
    return onChange;
  });
}

function attributeList(current: string) {
  const lists = screen.queryAllByRole("listbox", { hidden: true });
  return lists.find((list) => {
    const options = within(list);
    return (
      options.queryByRole("option", { name: current, hidden: true }) &&
      !options.queryByRole("option", { name: "Business Key", hidden: true })
    );
  });
}

describe("NodeConfigPanel grids", () => {
  const head = [
    attribute("sku", true),
    attribute("name"),
    attribute("qty"),
  ];

  beforeEach(() => {
    stubDomApis();
    vi.mocked(listEntities).mockResolvedValue({ items: [], total: 0, limit: 50, offset: 0 });
    vi.mocked(listVersions).mockResolvedValue({
      items: [version(head)],
      total: 1,
      limit: 50,
      offset: 0,
    });
  });

  afterEach(() => {
    cleanup();
  });

  it("shows each mapping column header once", async () => {
    await renderPanel(
      WRITE,
      node({
        entity_id: "ent_1",
        mode: "upsert",
        match_key: null,
        source: "rows",
        mapping: [
          { attribute: "sku", key: "sku" },
          { attribute: "name", key: "title" },
        ],
        on_incompatible_head: "fail",
      }),
    );

    expect(screen.getAllByText("Attribute")).toHaveLength(1);
    expect(screen.getAllByText("Source key")).toHaveLength(1);
    expect(screen.getAllByRole("combobox", { name: "Attribute" })).toHaveLength(2);
    expect(screen.getAllByRole("textbox", { name: "Source key" })).toHaveLength(2);
    expect(screen.getAllByRole("button", { name: "Remove" })).toHaveLength(2);
  });

  it("hides the mapping grid when the mode is delete and keeps the rows", async () => {
    const onChange = await renderPanel(
      WRITE,
      node({
        entity_id: "ent_1",
        mode: "delete",
        match_key: null,
        source: "rows",
        mapping: [{ attribute: "sku", key: "sku" }],
        on_incompatible_head: "fail",
      }),
    );

    expect(screen.queryByText("Mapping")).toBeNull();
    expect(screen.queryByRole("button", { name: "Remove" })).toBeNull();
    expect(onChange).not.toHaveBeenCalled();
  });

  it("omits attributes chosen on other mapping rows", async () => {
    await renderPanel(
      WRITE,
      node({
        entity_id: "ent_1",
        mode: "upsert",
        match_key: "sku",
        source: "rows",
        mapping: [
          { attribute: "sku", key: "sku" },
          { attribute: "name", key: "title" },
        ],
        on_incompatible_head: "fail",
      }),
    );

    await waitFor(() => {
      const list = attributeList("name");
      expect(list).toBeTruthy();
      expect(within(list!).queryByRole("option", { name: "qty", hidden: true })).toBeTruthy();
      expect(within(list!).queryByRole("option", { name: "sku", hidden: true })).toBeNull();
    });
    expect(screen.queryByText("Mapping must include sku")).toBeNull();
  });

  it("disables add when every head attribute is already mapped", async () => {
    await renderPanel(
      WRITE,
      node({
        entity_id: "ent_1",
        mode: "upsert",
        match_key: "sku",
        source: "rows",
        mapping: [
          { attribute: "sku", key: "sku" },
          { attribute: "name", key: "title" },
          { attribute: "qty", key: "qty" },
        ],
        on_incompatible_head: "fail",
      }),
    );

    await waitFor(() => {
      expect((screen.getByRole("button", { name: "Add" }) as HTMLButtonElement).disabled).toBe(
        true,
      );
    });
  });

  it("prompts when the resolved match key is missing from the mapping", async () => {
    await renderPanel(
      WRITE,
      node({
        entity_id: "ent_1",
        mode: "upsert",
        match_key: null,
        source: "rows",
        mapping: [{ attribute: "name", key: "title" }],
        on_incompatible_head: "fail",
      }),
    );

    expect(await screen.findByText("Mapping must include sku")).toBeTruthy();
  });

  it("keeps a repeated filter attribute available on every row", async () => {
    await renderPanel(
      READ,
      node(
        {
          entity_id: "ent_1",
          filters: [
            { attribute: "sku", op: "eq", value: "a" },
            { attribute: "name", op: "eq", value: "b" },
          ],
        },
        "read.entity",
      ),
    );

    expect(screen.getAllByText("Attribute")).toHaveLength(1);
    expect(screen.getAllByText("Operator")).toHaveLength(1);
    expect(screen.getAllByText("Value")).toHaveLength(1);
    await waitFor(() => {
      const list = attributeList("name");
      expect(list).toBeTruthy();
      expect(within(list!).queryByRole("option", { name: "sku", hidden: true })).toBeTruthy();
    });
  });
});
