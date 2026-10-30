/** @vitest-environment jsdom */

import { MantineProvider } from "@mantine/core";
import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { createElement, type ReactNode } from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import type { SchemaObject } from "@/features/channels/configSchemaForm";
import zh from "@/locales/zh-CN/common.json";
import type { FlowNodeData } from "@/features/channels/graphValidation";
import { problemIdentity } from "@/features/channels/problemLabel";
import type { ChannelTemplatePreview } from "@/features/channels/TemplateRunPreview";
import type { GraphProblem } from "@/features/channels/types";
import { listEntities, listVersions } from "@/features/entities/api";
import { listSources } from "@/features/sources/api/sources";
import type { Source } from "@/features/sources/types";
import type { EntityAttribute, EntityVersion } from "@/features/entities/types";

const zhMessages = zh as Record<string, string>;

const LABELS: Record<string, string> = {
  "channels.node.name": "Name",
  "channels.node.ref": "Ref",
  "channels.node.close": "Close",
  "channels.node.onError": "On error",
  "channels.node.onError.stop": "Stop",
  "channels.node.onError.continue": "Continue",
  "channels.node.onError.error_output": "Error output",
  "channels.node.retryMax": "Tries",
  "channels.node.retryMaxHint": "Includes the first try. Empty runs once.",
  "channels.node.retryWait": "Wait between tries (seconds)",
  "channels.node.retryWaitHint": "Checked for cancel and timeout while waiting.",
  "channels.config.addItem": "Add",
  "channels.config.removeItem": "Remove",
  "channels.config.businessKey": "Business Key",
  "channels.config.noAttributes": "No attributes",
  "channels.config.pickEntity": "Choose an Entity",
  "channels.config.attributeLoadFailed": "Could not load attributes",
  "channels.config.fields.entity_id": "Entity",
  "channels.config.fields.filters": "Filters",
  "channels.config.fields.attribute": "Attribute",
  "channels.config.fields.op": "Operator",
  "channels.config.fields.value": "Value",
  "channels.config.fields.mode": "Mode",
  "channels.config.fields.match_key": "Match key",
  "channels.config.fields.mapping": "Mapping",
  "channels.config.fields.payload": "Output",
  "channels.config.json.hint":
    'A JSON object copied into this node\'s output. Leave empty for {}. Example: {"status": "ready"}.',
  "channels.config.json.reserved":
    "triggered_by and triggered_at are added by the run. Remove them here.",
  "channels.config.fields.source": "Source",
  "channels.config.fields.statement_timeout_sec": "Statement timeout",
  "channels.config.fields.key": "Source key",
  "channels.config.listItem": "{{label}} {{n}}",
  "channels.config.fields.transform.filter.items": "Items",
  "channels.config.fields.transform.filter.combinator": "Combinator",
  "channels.config.fields.transform.filter.conditions": "Conditions",
  "channels.config.fields.transform.filter.key": "Field",
  "channels.config.fields.transform.filter.operator": "Operator",
  "channels.config.fields.transform.filter.value": "Value",
  "channels.config.fields.transform.merge.mode": "Mode",
  "channels.config.fields.transform.merge.inputs": "Inputs",
  "channels.config.fields.transform.merge.key": "Key",
  "channels.config.fields.transform.merge.join": "Join",
  "channels.config.fields.transform.set_fields.fields": "Fields",
  "channels.config.fields.transform.set_fields.name": "Name",
  "channels.config.fields.transform.set_fields.value": "Value",
  "channels.config.fields.transform.deduplicate.items": "Items",
  "channels.config.fields.transform.deduplicate.keys": "Keys",
  "channels.config.options.combinator.all": "All",
  "channels.config.options.operator.eq": "Equals",
  "channels.config.options.operator.is_null": "Is empty",
  "channels.config.options.mode.append": "Append",
  "channels.config.options.mode.by_key": "By key",
  "channels.config.options.join.inner": "Inner",
  "channels.config.fields.on_incompatible_head": "Incompatible head",
  "channels.config.options.mode.upsert": "Upsert",
  "channels.config.options.mode.delete": "Delete",
  "channels.config.options.op.eq": "Equals",
  "channels.config.options.on_incompatible_head.fail": "Fail",
  "channels.template.insert": "Insert calculation",
  "channels.template.recorded.title": "Recorded value",
  "channels.template.recorded.absent": "This run did not record a value for this field.",
  "channels.template.preview.title": "Preview",
  "channels.template.preview.pending": "Calculating",
  "channels.template.preview.fromScope": "Value from {{rounds}}, run started {{time}}",
  "channels.template.preview.fromRun": "Value from the run started {{time}}",
  "channels.template.preview.roundOf": "round {{n}} of {{name}}",
  "channels.template.preview.empty": "Empty string",
  "channels.template.resultString":
    "The result type is string. Quotes inside an expression are not part of the result.",
  "channels.template.ruleText": "The whole text is the value. Quotes are not needed.",
  "channels.config.fields.sql": "SQL",
  "channels.config.fields.transform.code.code": "Code",
  "channels.config.fields.transform.code.code.description": "Python body of main.",
  "channels.config.fields.read.source_query.source_id": "Source",
  "channels.config.fields.read.source_query.source_id.description": "Registered Source.",
  "channels.config.fields.read.changes.entity_id":
    zhMessages["channels.config.fields.read.changes.entity_id"],
  "channels.config.fields.read.changes.entity_id.description":
    zhMessages["channels.config.fields.read.changes.entity_id.description"],
  "channels.config.fields.read.changes.sources":
    zhMessages["channels.config.fields.read.changes.sources"],
  "channels.config.fields.read.changes.sources.description":
    zhMessages["channels.config.fields.read.changes.sources.description"],
  "channels.config.fields.transform.merge.inputs.description": "Locale lists.",
  "channels.config.source.placeholder": "Select a source",
  "channels.config.source.loadFailed": "Could not load sources",
  "form.field.description": "Description",
  "form.field.status": "Problems",
  "problems.CHANNEL_NODE_CONFIG_INVALID": "A node configuration is invalid",
  "problems.CHANNEL_GRAPH_UNREACHABLE": "A node is unreachable from the trigger",
  "problems.CHANNEL_TEMPLATE_TYPE_UNKNOWN": "Checked at run time",
  "problems.CHANNEL_EXPRESSION_INVALID": "A template expression does not parse",
};

vi.mock("@refinedev/core", () => ({
  useTranslate: () => (key: string, values?: Record<string, unknown>) => {
    const template = LABELS[key] ?? key;
    if (!values) return template;
    return template.replace(/\{\{(\w+)\}\}/g, (_, name: string) => String(values[name] ?? ""));
  },
  usePermissions: () => ({ data: [] as string[] }),
}));

vi.mock("@/features/sources/api/sources", () => ({
  listSources: vi.fn(async () => ({ items: [], total: 0, limit: 100, offset: 0 })),
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
    trigger: false,
    container: null,
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
  if (document.fonts == null) {
    Object.defineProperty(document, "fonts", {
      configurable: true,
      value: { addEventListener() {}, removeEventListener() {} },
    });
  }
  const rect = () => ({
    x: 0,
    y: 0,
    top: 0,
    left: 0,
    bottom: 0,
    right: 0,
    width: 0,
    height: 0,
    toJSON() {
      return {};
    },
  });
  document.elementFromPoint = () => null;
  Range.prototype.getBoundingClientRect = rect;
  Range.prototype.getClientRects = () => ({
    length: 0,
    item: () => null,
    [Symbol.iterator]: function* empty() {
      yield* [];
    },
  }) as unknown as () => DOMRectList;
}

function renderPanel(
  schema: SchemaObject,
  data: FlowNodeData,
  onChange = vi.fn(),
  problems: GraphProblem[] = [],
  editable = true,
  revealKey: string | null = null,
  templatePreview: ChannelTemplatePreview | null = null,
  sample: {
    recordedInput?: Record<string, unknown> | null;
    baselineConfig?: Record<string, unknown> | null;
    sampleScope?: { container_node_id: string; round: number }[];
    runTime?: string | null;
    onTemplateCaret?: (caret: { write: (from: number, to: number, text: string) => void } | null) => void;
  } = {},
) {
  return import("@/features/channels/NodeConfigPanel").then(({ NodeConfigPanel }) => {
    render(
      createElement(
        MantineProvider,
        { env: "test" },
        createElement(NodeConfigPanel, {
          nodeId: "n1",
          data,
          spec: null,
          schema,
          editable,
          canRun: null,
          problems,
          revealKey,
          scope: { nodes: [], context: { channel: null, run: null, platform: null } },
          templatePreview,
          recordedInput: sample.recordedInput,
          baselineConfig: sample.baselineConfig,
          sampleScope: sample.sampleScope,
          runTime: sample.runTime,
          onTemplateCaret: sample.onTemplateCaret,
          upstream: null,
          result: null,
          onClose: vi.fn(),
          onChange,
          onRun: vi.fn(),
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

const PAYLOAD: SchemaObject = {
  type: "object",
  properties: {
    payload: { type: "object", "x-refraq-ref": "json" },
  },
};

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

  it("puts a mapping cell problem on the mapping label and leaves the cell unmarked", async () => {
    await renderPanel(
      WRITE,
      node({
        entity_id: "ent_1",
        mode: "upsert",
        match_key: null,
        source: "rows",
        mapping: [{ attribute: "sku", key: "sku" }],
        on_incompatible_head: "fail",
      }),
      vi.fn(),
      [
        {
          code: "CHANNEL_NODE_CONFIG_INVALID",
          node_id: "n1",
          edge_id: null,
          path: ["mapping", 0, "attribute"],
          detail: "'' should be non-empty",
        },
      ],
    );

    const cell = screen.getAllByRole("combobox", { name: "Attribute" })[0];
    expect(cell?.getAttribute("aria-invalid")).not.toBe("true");
    expect(screen.queryByText(/should be non-empty/)).toBeNull();
    fireEvent.click(screen.getByRole("button", { name: "Mapping Problems" }));
    expect(
      screen.getByText(
        "A node configuration is invalid: mapping.0.attribute — '' should be non-empty",
      ),
    ).toBeTruthy();
    expect(document.querySelector(".channel-config-grid")?.textContent ?? "").not.toContain(
      "should be non-empty",
    );
  });

  it("shows the mapping grid when the mode is delete", async () => {
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

    expect(screen.queryByText("Mapping")).toBeTruthy();
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

describe("NodeConfigPanel integers", () => {
  beforeEach(stubDomApis);
  afterEach(cleanup);

  it("shows the timeout constraint on that field and omits the key when the field is cleared", async () => {
    const onChange = vi.fn();
    await renderPanel(
      {
        type: "object",
        properties: {
          statement_timeout_sec: {
            type: "integer",
            minimum: 1,
            maximum: 3600,
            description: "Seconds before the statement is cancelled. Default 30.",
          },
        },
      },
      node({ statement_timeout_sec: 12 }, "read.sql"),
      onChange,
      [
        {
          code: "CHANNEL_NODE_CONFIG_INVALID",
          node_id: "n1",
          edge_id: null,
          path: ["statement_timeout_sec"],
          detail: "None is not of type 'integer'",
        },
      ],
    );

    const timeout = screen.getByRole("textbox", { name: "Statement timeout" });
    expect(timeout.closest(".field-chrome")?.textContent ?? "").not.toContain(
      "Seconds before the statement is cancelled",
    );
    expect(
      screen.queryByText(
        "A node configuration is invalid: statement_timeout_sec — None is not of type 'integer'",
      ),
    ).toBeNull();
    fireEvent.click(screen.getByRole("button", { name: "Statement timeout Description" }));
    expect(screen.getByText("Seconds before the statement is cancelled. Default 30.")).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "Statement timeout Problems" }));
    expect(
      screen.getAllByText(
        "A node configuration is invalid: statement_timeout_sec — None is not of type 'integer'",
      ),
    ).toHaveLength(1);

    fireEvent.change(screen.getByRole("textbox", { name: "Statement timeout" }), {
      target: { value: "" },
    });
    expect(onChange).toHaveBeenCalled();
    const next = onChange.mock.calls.at(-1)?.[1] as FlowNodeData;
    expect(next.config).not.toHaveProperty("statement_timeout_sec");
  });

  it("offers stop and continue after the node fields", async () => {
    const onChange = await renderPanel(PAYLOAD, node({ payload: {} }, "trigger.manual"));

    const select = screen.getByRole("combobox", { name: "On error" }) as HTMLInputElement;
    expect(select.value).toBe("Stop");
    fireEvent.change(screen.getByRole("textbox", { name: "Tries" }), { target: { value: "3" } });
    const next = onChange.mock.calls.at(-1)?.[1] as FlowNodeData;
    expect(next.retry).toEqual({ max_tries: 3, wait_sec: 0 });
  });

  it("lets an unsupported on-error value be reset to stop", async () => {
    await renderPanel(PAYLOAD, { ...node({ payload: {} }, "trigger.manual"), onError: "continue" });

    const select = screen.getByRole("combobox", { name: "On error" }) as HTMLInputElement;
    expect(select.value).toBe("Continue");
  });

  it("keeps a node-level problem on the title and opens it from the problem list", async () => {
    const problem: GraphProblem = {
      code: "CHANNEL_GRAPH_UNREACHABLE",
      node_id: "n1",
      edge_id: null,
      path: [],
      detail: "Node is not reachable",
    };
    await renderPanel(
      { type: "object", properties: {} },
      node({}),
      vi.fn(),
      [problem],
      true,
      problemIdentity(problem),
    );

    expect(document.querySelector(".channel-node-detail")?.textContent ?? "").not.toContain(
      "A node is unreachable from the trigger",
    );
    expect(screen.getByText("A node is unreachable from the trigger")).toBeTruthy();
  });

  it("puts name and ref problems on their own labeled fields", async () => {
    const duplicateRef: GraphProblem = {
      code: "CHANNEL_NODE_REF_INVALID",
      node_id: "n1",
      edge_id: null,
      path: [],
      detail: "Node ref is duplicated",
    };
    await renderPanel(
      { type: "object", properties: {} },
      node({}),
      vi.fn(),
      [
        {
          code: "CHANNEL_NODE_NAME_DUP",
          node_id: "n1",
          edge_id: null,
          path: [],
          detail: "Node name is duplicated",
        },
        duplicateRef,
      ],
      true,
      problemIdentity(duplicateRef),
    );

    expect(screen.getByText("Name").closest("label")).not.toBeNull();
    expect(screen.getByText("Ref").closest("label")).not.toBeNull();
    expect(screen.queryByRole("button", { name: "Step Problems" })).toBeNull();
    expect(screen.getByRole("button", { name: "Name Problems" })).toBeTruthy();
    expect(screen.getByRole("button", { name: "Ref Problems" })).toBeTruthy();
    expect(screen.getByRole("textbox", { name: "Ref" }).getAttribute("aria-invalid")).toBe("true");
    expect(screen.getByText("Node ref is duplicated")).toBeTruthy();
    expect(screen.queryByText("Node name is duplicated")).toBeNull();
  });
});

describe("NodeConfigPanel display mode", () => {
  beforeEach(stubDomApis);
  afterEach(cleanup);

  it("shows a template statement as the same document when the panel is closed for editing", async () => {
    await renderPanel(
      {
        type: "object",
        properties: {
          sql: {
            type: "string",
            description: "The query",
            "x-refraq-template": { type: "string" },
          },
        },
      },
      node({ sql: "select\n1" }, "read.sql"),
      vi.fn(),
      [],
      false,
    );

    expect(screen.queryByRole("button", { name: "Insert calculation" })).toBeNull();
    expect(screen.queryByText("The query")).toBeNull();
    fireEvent.click(screen.getByRole("button", { name: "SQL Description" }));
    expect(screen.getByText("The query")).toBeTruthy();
    const content = document.querySelector(".cm-content");
    expect(content?.getAttribute("contenteditable")).toBe("false");
    expect(
      [...document.querySelectorAll(".cm-line")].map((line) => line.textContent),
    ).toEqual(["select", "1"]);
  });

  it("states the splice rule and paints a warning apart from an error", async () => {
    const schema: SchemaObject = {
      type: "object",
      properties: {
        sql: {
          type: "string",
          description: "The query",
          "x-refraq-template": { type: "string" },
        },
      },
    };
    await renderPanel(schema, node({ sql: 'select {{ "abc" }}' }, "read.sql"), vi.fn(), [
      {
        code: "CHANNEL_TEMPLATE_TYPE_UNKNOWN",
        node_id: "n1",
        edge_id: null,
        path: ["sql"],
        detail: "Template result type is not known until the node runs",
        severity: "warning",
      },
    ]);

    const sqlField = document.querySelector(".channel-template-field");
    expect(sqlField?.textContent ?? "").not.toContain(
      "The result type is string. Quotes inside an expression are not part of the result.",
    );
    fireEvent.click(screen.getByRole("button", { name: "SQL Problems" }));
    expect(
      screen.getByText(
        "The result type is string. Quotes inside an expression are not part of the result.",
      ),
    ).toBeTruthy();
    expect(screen.queryByText("The whole text is the value. Quotes are not needed.")).toBeNull();
    expect(document.querySelector(".channel-template-field__editor")?.getAttribute("data-severity")).toBe(
      "warning",
    );
    expect(document.querySelector(".cm-content")?.getAttribute("aria-invalid")).toBe("false");

    cleanup();
    await renderPanel(schema, node({ sql: "{{ 1 }}" }, "read.sql"), vi.fn(), [
      {
        code: "CHANNEL_TEMPLATE_TYPE_UNKNOWN",
        node_id: "n1",
        edge_id: null,
        path: ["sql"],
        detail: "Template result type is not known until the node runs",
        severity: "warning",
      },
      {
        code: "CHANNEL_EXPRESSION_INVALID",
        node_id: "n1",
        edge_id: null,
        path: ["sql"],
        detail: "Template expression does not parse",
      },
    ]);

    expect(document.querySelector(".channel-template-field__editor")?.getAttribute("data-severity")).toBe(
      "error",
    );
    expect(document.querySelector(".cm-content")?.getAttribute("aria-invalid")).toBe("true");
    fireEvent.click(screen.getByRole("button", { name: "SQL Problems" }));
    expect(
      screen.getByText(
        "Checked at run time: sql — Template result type is not known until the node runs",
      ),
    ).toBeTruthy();
    expect(
      screen.getByText(
        "A template expression does not parse: sql — Template expression does not parse",
      ),
    ).toBeTruthy();
    expect(document.querySelector(".channel-template-field__editor")?.textContent ?? "").not.toContain(
      "A template expression does not parse",
    );
  });

  it("shows the recorded input until the template differs from the run snapshot", async () => {
    const schema: SchemaObject = {
      type: "object",
      properties: {
        sql: { type: "string", "x-refraq-template": { type: "string" } },
      },
    };
    const scope = [{ container_node_id: "loop", round: 1 }];
    const evaluate = vi.fn().mockResolvedValue({
      state: "ok",
      value: "select 9",
      truncated: false,
      scope: [{ container_node_id: "loop", container_seq: 2, round: 1, rounds_total: 4 }],
      bindings: [],
    });
    const sample = {
      recordedInput: { sql: { value: "select 6" } },
      baselineConfig: { sql: "select {{ 6 }}" },
      sampleScope: scope,
      runTime: "Jan 2",
    };
    await renderPanel(schema, node({ sql: "select {{ 6 }}" }, "read.sql"), vi.fn(), [], true, null, {
      run: { key: "run-1", evaluate },
    }, sample);

    expect(screen.getByText("Recorded value")).toBeTruthy();
    expect(document.querySelector(".channel-template-field__recorded")?.textContent).toBe("select 6");
    expect(evaluate).not.toHaveBeenCalled();

    cleanup();
    await renderPanel(schema, node({ sql: "select {{ 9 }}" }, "read.sql"), vi.fn(), [], true, null, {
      run: { key: "run-1", evaluate },
    }, sample);
    await waitFor(() => {
      expect(evaluate).toHaveBeenCalledWith("n1", ["sql"], scope);
    });
    expect(document.querySelector(".channel-template-field__value")?.textContent).toBe("select 9");
    expect(screen.getByText("Value from round 2 of loop, run started Jan 2")).toBeTruthy();
    expect(screen.queryByText("Recorded value")).toBeNull();
  });

  it("keeps the recorded value when the field cannot be previewed", async () => {
    const schema: SchemaObject = {
      type: "object",
      properties: {
        sql: { type: "string", "x-refraq-template": { type: "string" } },
      },
    };
    await renderPanel(
      schema,
      node({ sql: "select {{ 9 }}" }, "read.sql"),
      vi.fn(),
      [],
      false,
      null,
      null,
      {
        recordedInput: { sql: { value: "select 6" } },
        baselineConfig: { sql: "select {{ 6 }}" },
      },
    );
    expect(document.querySelector(".channel-template-field__recorded")?.textContent).toBe("select 6");
    expect(screen.queryByText("Preview")).toBeNull();
    expect(screen.queryByRole("button", { name: "Insert calculation" })).toBeNull();
  });

  it("shows an unclosed expression before a problem is attached", async () => {
    await renderPanel(
      {
        type: "object",
        properties: {
          sql: {
            type: "string",
            "x-refraq-template": { type: "string" },
          },
        },
      },
      node({ sql: "{{ " }, "read.sql"),
    );

    expect(screen.queryByText("A template expression does not parse")).toBeNull();
    fireEvent.click(screen.getByRole("button", { name: "SQL Problems" }));
    expect(screen.getByText("A template expression does not parse")).toBeTruthy();
    expect(document.querySelector(".channel-template-field__editor")?.getAttribute("data-severity")).toBeNull();
  });

  it("shows an empty object and the JSON format", async () => {
    await renderPanel(PAYLOAD, node({ payload: {} }, "trigger.manual"));
    const box = screen.getByRole("textbox", { name: "Output" }) as HTMLTextAreaElement;
    expect(box.value).toBe("{}");
    expect(screen.getByText(/Example: \{"status": "ready"\}/)).toBeTruthy();
  });

  it("writes a JSON object and leaves invalid text out of the config", async () => {
    const onChange = await renderPanel(PAYLOAD, node({ payload: {} }, "trigger.manual"));
    const box = screen.getByRole("textbox", { name: "Output" });
    fireEvent.change(box, { target: { value: '{"status":"ready"}' } });
    fireEvent.blur(box);
    expect(onChange).toHaveBeenCalledWith(
      "n1",
      expect.objectContaining({
        config: expect.objectContaining({ payload: { status: "ready" } }),
      }),
    );

    fireEvent.change(box, { target: { value: "not-json" } });
    fireEvent.blur(box);
    expect(onChange).toHaveBeenCalledTimes(1);
    expect(box.getAttribute("aria-invalid")).toBe("true");
    expect((box as HTMLTextAreaElement).value).toBe("not-json");
  });

  it("shows a stored JSON string as typed and stores the object", async () => {
    const raw = '{"triggered_at": "2026-10-14T06:01:20.717698Z"}';
    const onChange = await renderPanel(
      PAYLOAD,
      node({ payload: raw }, "trigger.manual"),
      vi.fn(),
      [
        {
          code: "CHANNEL_NODE_CONFIG_INVALID",
          node_id: "n1",
          edge_id: null,
          path: ["payload"],
          detail: `'${raw}' is not of type 'object'`,
        },
      ],
    );
    const box = screen.getByRole("textbox", { name: "Output" }) as HTMLTextAreaElement;
    expect(box.value).toBe(raw);
    expect(screen.queryByText(/is not of type/)).toBeNull();
    await waitFor(() => {
      expect(onChange).toHaveBeenCalledWith(
        "n1",
        expect.objectContaining({
          config: expect.objectContaining({
            payload: { triggered_at: "2026-10-14T06:01:20.717698Z" },
          }),
        }),
      );
    });
  });

  it("explains reserved payload keys on the output field", async () => {
    await renderPanel(
      PAYLOAD,
      node({ payload: { triggered_at: "2026-10-14T06:01:20.717698Z" } }, "trigger.manual"),
      vi.fn(),
      [
        {
          code: "CHANNEL_NODE_CONFIG_INVALID",
          node_id: "n1",
          edge_id: null,
          path: ["payload"],
          detail: "Manual payload uses a reserved key",
        },
      ],
    );
    expect(screen.queryByText(/reserved key/)).toBeNull();
    fireEvent.click(screen.getByRole("button", { name: "Output Problems" }));
    expect(screen.getByText(/added by the run/)).toBeTruthy();
  });
});

const ANY_TEMPLATE = { type: "string", "x-refraq-template": { type: "string" } } as const;

const FILTER_SCHEMA: SchemaObject = {
  type: "object",
  properties: {
    items: { type: "string", "x-refraq-template": { type: "array", items: { type: "object" } } },
    combinator: { type: "string", enum: ["all", "any"], default: "all" },
    conditions: {
      type: "array",
      description: "Comparisons.",
      items: {
        type: "object",
        required: ["key", "operator"],
        properties: {
          key: { type: "string" },
          operator: {
            type: "string",
            enum: ["eq", "is_null", "is_not_null"],
          },
          value: ANY_TEMPLATE,
        },
        allOf: [
          {
            if: { properties: { operator: { enum: ["eq"] } }, required: ["operator"] },
            then: { required: ["value"] },
          },
        ],
      },
    },
  },
};

const MERGE_SCHEMA: SchemaObject = {
  type: "object",
  properties: {
    mode: { type: "string", enum: ["append", "by_key", "by_position"] },
    inputs: {
      type: "array",
      description: "Lists to fold.",
      items: {
        type: "string",
        description: "One list.",
        "x-refraq-template": { type: "array", items: { type: "object" } },
      },
    },
    key: { type: ["string", "null"] },
    join: {
      type: "string",
      enum: ["inner", "left", "full"],
      default: "inner",
      description: "append ignores it.",
    },
  },
  allOf: [
    {
      if: { properties: { mode: { const: "by_key" } }, required: ["mode"] },
      then: { required: ["key"] },
    },
  ],
};

describe("reshape node configuration", () => {
  beforeEach(stubDomApis);
  afterEach(cleanup);

  it("edits filter conditions and hides the value for an emptiness check", async () => {
    const onChange = await renderPanel(
      FILTER_SCHEMA,
      node(
        {
          items: "{{ self.read.output.rows }}",
          combinator: "all",
          conditions: [{ key: "code", operator: "eq", value: '"A"' }],
        },
        "transform.filter",
      ),
    );

    expect(screen.getByRole("combobox", { name: "Combinator" })).toBeTruthy();
    expect(screen.getByRole("textbox", { name: "Field" })).toBeTruthy();
    expect((screen.getByRole("combobox", { name: "Operator" }) as HTMLInputElement).value).toBe(
      "Equals",
    );
    await waitFor(() => {
      expect(screen.getByRole("textbox", { name: "Value" })).toBeTruthy();
    });

    fireEvent.mouseDown(screen.getByRole("combobox", { name: "Operator" }));
    const lists = screen.getAllByRole("listbox", { hidden: true });
    const list = lists.find((item) => within(item).queryByRole("option", { name: "Is empty", hidden: true }));
    if (!list) throw new Error("missing operator list");
    fireEvent.click(within(list).getByRole("option", { name: "Is empty", hidden: true }));
    const changed = onChange.mock.calls.at(-1)?.[1] as FlowNodeData;
    expect(changed.config.conditions).toEqual([{ key: "code", operator: "is_null", value: '"A"' }]);

    cleanup();
    await renderPanel(
      FILTER_SCHEMA,
      node(
        {
          items: "{{ self.read.output.rows }}",
          combinator: "all",
          conditions: [{ key: "code", operator: "is_null" }],
        },
        "transform.filter",
      ),
    );
    expect(screen.queryByRole("textbox", { name: "Value" })).toBeNull();
    expect(screen.getByRole("textbox", { name: "Field" })).toBeTruthy();
  });

  it("gives a nested template the same insert control and recorded value", async () => {
    await renderPanel(
      FILTER_SCHEMA,
      node(
        {
          items: "{{ self.read.output.rows }}",
          combinator: "all",
          conditions: [{ key: "code", operator: "eq", value: '"A"' }],
        },
        "transform.filter",
      ),
      vi.fn(),
      [],
      true,
      null,
      null,
      {
        recordedInput: {
          items: { value: [{ code: "S" }] },
          "conditions.0.value": { error: { code: "CHANNEL_NODE_FAILED", message: "bad value" } },
        },
        baselineConfig: {
          items: "{{ self.read.output.rows }}",
          conditions: [{ key: "code", operator: "eq", value: '"A"' }],
        },
      },
    );
    expect(screen.getAllByRole("button", { name: "Insert calculation" }).length).toBeGreaterThan(1);
    expect(screen.getByText("bad value")).toBeTruthy();
    expect(screen.getByText((text) => text.includes('"code"') && text.includes("S"))).toBeTruthy();
  });

  it("edits merge inputs and shows the key only for a key join", async () => {
    const onChange = await renderPanel(
      MERGE_SCHEMA,
      node({ mode: "append", inputs: ["{{ self.left.output.rows }}"], key: null, join: "inner" }, "transform.merge"),
    );
    expect(screen.queryByRole("textbox", { name: "Key" })).toBeNull();
    expect(screen.getByRole("combobox", { name: "Join" })).toBeTruthy();
    await waitFor(() => {
      expect(screen.getByRole("textbox", { name: "Inputs 1" })).toBeTruthy();
    });
    fireEvent.click(screen.getByRole("button", { name: "Add" }));
    const next = onChange.mock.calls.at(-1)?.[1] as FlowNodeData;
    expect(next.config.inputs).toEqual(["{{ self.left.output.rows }}", ""]);

    cleanup();
    await renderPanel(
      MERGE_SCHEMA,
      node({ mode: "by_key", inputs: [], key: "code", join: "inner" }, "transform.merge"),
    );
    expect((screen.getByRole("textbox", { name: "Key" }) as HTMLInputElement).value).toBe("code");
    expect((screen.getByRole("combobox", { name: "Join" }) as HTMLInputElement).value).toBe("Inner");
  });

  it("adds a set-fields entry with a name and a template value", async () => {
    const onChange = await renderPanel(
      {
        type: "object",
        properties: {
          fields: {
            type: "array",
            description: "Keys to write.",
            items: {
              type: "object",
              properties: {
                name: { type: "string" },
                value: ANY_TEMPLATE,
              },
            },
          },
        },
      },
      node({ fields: [{ name: "code", value: '"A"' }] }, "transform.set_fields"),
    );
    expect(screen.getAllByRole("textbox", { name: "Name" }).length).toBeGreaterThan(1);
    await waitFor(() => {
      expect(screen.getByRole("textbox", { name: "Value" })).toBeTruthy();
    });
    fireEvent.click(screen.getByRole("button", { name: "Add" }));
    const next = onChange.mock.calls.at(-1)?.[1] as FlowNodeData;
    expect(next.config.fields).toEqual([
      { name: "code", value: '"A"' },
      { name: "", value: "" },
    ]);
  });

  it("adds a deduplicate key", async () => {
    const onChange = await renderPanel(
      {
        type: "object",
        properties: {
          items: { type: "string", "x-refraq-template": { type: "array" } },
          keys: { type: "array", description: "Identity fields.", items: { type: "string" } },
        },
      },
      node({ items: "{{ self.read.output.rows }}", keys: ["code"] }, "transform.deduplicate"),
    );
    const key = screen.getByRole("textbox", { name: "Keys 1" }) as HTMLInputElement;
    expect(key.value).toBe("code");
    fireEvent.click(screen.getByRole("button", { name: "Add" }));
    const next = onChange.mock.calls.at(-1)?.[1] as FlowNodeData;
    expect(next.config.keys).toEqual(["code", ""]);
  });
});

function listedSource(id: string, name: string): Source {
  return {
    id,
    key: id,
    locator_key: id,
    name,
    kind: "database",
    status: "active",
    description: null,
    engine: "postgresql",
    access: null,
    has_access: true,
    access_updated_at: null,
  };
}

describe("code and source query fields", () => {
  beforeEach(stubDomApis);
  afterEach(cleanup);

  it("renders python in a code editor named by the field label", async () => {
    await renderPanel(
      {
        type: "object",
        properties: {
          code: {
            type: "string",
            description: "Schema description",
            contentMediaType: "text/x-python",
          },
        },
      },
      node({ code: "return 1" }, "transform.code"),
    );

    const editor = screen.getByRole("textbox", { name: "Code" });
    expect(editor.getAttribute("contenteditable")).toBe("true");
    expect(
      [...document.querySelectorAll(".cm-line")].map((line) => line.textContent),
    ).toEqual(["return 1"]);
    fireEvent.click(screen.getByRole("button", { name: "Code Description" }));
    expect(screen.getByText("Python body of main.")).toBeTruthy();
    expect(screen.queryByText("Schema description")).toBeNull();
  });

  it("lists registered sources and stores the chosen id", async () => {
    vi.mocked(listSources).mockResolvedValue({
      items: [listedSource("src_wh", "Warehouse"), listedSource("src_arc", "Archive")],
      total: 2,
      limit: 100,
      offset: 0,
    });
    const onChange = await renderPanel(
      {
        type: "object",
        properties: {
          source_id: {
            type: "string",
            description: "Schema description",
            "x-refraq-ref": "source",
          },
        },
      },
      node({ source_id: "src_wh" }, "read.source_query"),
    );

    await waitFor(() => {
      expect((screen.getByRole("combobox", { name: "Source" }) as HTMLInputElement).value).toBe(
        "Warehouse",
      );
    });
    fireEvent.click(screen.getByRole("button", { name: "Source Description" }));
    expect(screen.getByText("Registered Source.")).toBeTruthy();

    fireEvent.mouseDown(screen.getByRole("combobox", { name: "Source" }));
    const lists = screen.getAllByRole("listbox", { hidden: true });
    const list = lists.find((item) =>
      within(item).queryByRole("option", { name: "Archive", hidden: true }),
    );
    if (!list) throw new Error("missing source list");
    fireEvent.click(within(list).getByRole("option", { name: "Archive", hidden: true }));
    const changed = onChange.mock.calls.at(-1)?.[1] as FlowNodeData;
    expect(changed.config.source_id).toBe("src_arc");
  });
});

const SCHEMA_ENTITY = "Business Entity whose Change Log is read.";
const SCHEMA_SOURCES =
  "Optional subset of user, channel_run, and unattributed. Absent or empty returns every source. Hidden entries still advance the cursor.";

describe("read.changes field descriptions", () => {
  beforeEach(stubDomApis);
  afterEach(cleanup);

  it("shows the locale sentences for entity and sources, not the schema English", async () => {
    await renderPanel(
      {
        type: "object",
        required: ["entity_id"],
        properties: {
          entity_id: {
            type: "string",
            description: SCHEMA_ENTITY,
            "x-refraq-ref": "entity",
          },
          sources: {
            type: "array",
            description: SCHEMA_SOURCES,
            items: { type: "string", enum: ["user", "channel_run", "unattributed"] },
          },
        },
      },
      node({ entity_id: "", sources: [] }, "read.changes"),
    );

    const entityLabel = zhMessages["channels.config.fields.read.changes.entity_id"];
    const entityDescription =
      zhMessages["channels.config.fields.read.changes.entity_id.description"];
    const sourcesLabel = zhMessages["channels.config.fields.read.changes.sources"];
    const sourcesDescription =
      zhMessages["channels.config.fields.read.changes.sources.description"];

    fireEvent.click(screen.getByRole("button", { name: `${entityLabel} Description` }));
    expect(screen.getByText(entityDescription)).toBeTruthy();
    expect(screen.queryByText(SCHEMA_ENTITY)).toBeNull();

    fireEvent.click(screen.getByRole("button", { name: `${sourcesLabel} Description` }));
    expect(screen.getByText(sourcesDescription)).toBeTruthy();
    expect(screen.queryByText(SCHEMA_SOURCES)).toBeNull();
  });

  it("uses the locale sentence for a template list when the key exists", async () => {
    await renderPanel(MERGE_SCHEMA, node({ mode: "append", inputs: [] }, "transform.merge"));
    fireEvent.click(screen.getByRole("button", { name: "Inputs Description" }));
    expect(screen.getByText("Locale lists.")).toBeTruthy();
    expect(screen.queryByText("Lists to fold.")).toBeNull();
  });
});
