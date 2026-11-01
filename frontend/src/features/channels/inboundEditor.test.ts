/** @vitest-environment jsdom */

import { MantineProvider } from "@mantine/core";
import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { createElement, useState, type ReactNode } from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { listInboundCredentials } from "@/features/inbound-credentials/api";
import type { InboundCredential } from "@/features/inbound-credentials/types";
import { copyText } from "@/lib/copy-text";
import type { SchemaObject } from "@/features/channels/configSchemaForm";
import type { FlowNodeData } from "@/features/channels/graphValidation";
import { respondNodeOffered } from "@/features/channels/paletteOffer";
import { EMPTY_GRAPH, type Graph, type NodeTypeSpec } from "@/features/channels/types";

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
  "channels.node.config": "Configuration",
  "channels.config.addItem": "Add",
  "channels.config.removeItem": "Remove",
  "channels.config.fields.trigger.inbound.path": "Path",
  "channels.config.fields.trigger.inbound.allow_get": "Allow GET",
  "channels.config.fields.trigger.inbound.credential_id": "Credential",
  "channels.config.fields.trigger.inbound.input": "Input",
  "channels.config.fields.trigger.inbound.name": "Name",
  "channels.config.fields.trigger.inbound.input.type": "Type",
  "channels.config.fields.trigger.inbound.input.required": "Required",
  "channels.config.fields.trigger.inbound.event_id.from": "Event id from",
  "channels.config.fields.trigger.inbound.event_id.key": "Event id key",
  "channels.config.fields.trigger.inbound.dedup_window_sec": "Dedup window",
  "channels.config.fields.trigger.inbound.max_in_flight": "In-flight cap",
  "channels.config.fields.trigger.inbound.response": "Response",
  "channels.config.fields.trigger.inbound.response.mode": "Mode",
  "channels.config.fields.trigger.inbound.response.status": "Status",
  "channels.config.fields.trigger.inbound.response.content_type": "Content type",
  "channels.config.fields.trigger.inbound.response.headers": "Headers",
  "channels.config.fields.trigger.inbound.response.body.kind": "Kind",
  "channels.config.fields.trigger.inbound.response.body.text": "Text",
  "channels.config.fields.trigger.inbound.response.body.from": "Echo from",
  "channels.config.fields.trigger.inbound.response.body.key": "Echo key",
  "channels.config.fields.trigger.inbound.response.wait_sec": "Wait",
  "channels.config.fields.trigger.inbound.response.fallback.status": "Fallback status",
  "channels.config.fields.trigger.inbound.response.fallback.body": "Fallback body",
  "channels.config.fields.trigger.inbound.sample_request": "Sample request",
  "channels.config.fields.trigger.inbound.sample_request.method": "Method",
  "channels.config.fields.trigger.inbound.sample_request.headers": "Headers",
  "channels.config.fields.trigger.inbound.sample_request.query": "Query",
  "channels.config.fields.trigger.inbound.sample_request.body": "Body",
  "channels.config.fields.trigger.inbound.value": "Value",
  "channels.config.fields.trigger.inbound.public_url": "Public URL",
  "channels.config.fields.trigger.inbound.copy_url": "Copy public URL",
  "channels.config.options.inbound_mode.immediate": "Immediate",
  "channels.config.options.inbound_mode.respond_node": "Respond node",
  "channels.config.options.inbound_kind.static": "Static",
  "channels.config.options.inbound_kind.echo": "Echo",
  "channels.config.options.inbound_from.header": "Header",
  "channels.config.options.inbound_from.query": "Query",
  "channels.config.options.inbound_from.body": "Body",
  "channels.config.options.inbound_type.string": "String",
  "channels.config.options.inbound_type.integer": "Integer",
  "channels.config.options.inbound_type.number": "Number",
  "channels.config.options.inbound_type.boolean": "Boolean",
  "channels.config.options.inbound_type.object": "Object",
  "channels.config.options.inbound_type.array": "Array",
  "channels.config.fields.action.respond.status": "Status",
  "channels.config.fields.action.respond.content_type": "Content type",
  "channels.config.fields.action.respond.headers": "Headers",
  "channels.config.fields.action.respond.body": "Body",
  "channels.config.fields.action.respond.name": "Name",
  "channels.config.fields.action.respond.value": "Value",
  "channels.template.insert": "Insert calculation",
  "channels.template.ruleText": "The whole text is the value.",
  "inboundCredentials.picker.placeholder": "Select a credential",
  "inboundCredentials.picker.missing": "Missing credential",
  "inboundCredentials.picker.loadFailed": "Could not load credentials",
  "inboundCredentials.types.token": "Token",
  "common.copy.success": "Copied",
  "common.copy.failed": "Could not copy",
};

vi.mock("@refinedev/core", () => ({
  useTranslate: () => (key: string, options?: { defaultValue?: string }) =>
    LABELS[key] ?? options?.defaultValue ?? key,
  usePermissions: () => ({ data: [] as string[] }),
  useNotification: () => ({ open: vi.fn() }),
}));

vi.mock("@/features/inbound-credentials/api", () => ({
  listInboundCredentials: vi.fn(),
  getInboundCredential: vi.fn(),
}));

vi.mock("@/lib/copy-text", () => ({
  copyText: vi.fn(() => Promise.resolve()),
}));

const now = "2026-01-01T00:00:00Z";

const PARTNER: InboundCredential = {
  id: "icr_1",
  name: "Partner",
  type: "token",
  config: { location: "header", name: "X-Token" },
  created_at: now,
  updated_at: now,
};

const RESPOND: SchemaObject = {
  type: "object",
  required: ["status"],
  properties: {
    status: {
      type: "string",
      minLength: 1,
      title: "Status",
      description: "Template that renders to an integer HTTP status from 100 to 599.",
      "x-refraq-template": { type: "integer", minimum: 100, maximum: 599 },
    },
    content_type: {
      type: "string",
      default: "application/json",
      title: "Content type",
      description: "Template for the response content type. Omitted means application/json.",
      "x-refraq-template": { type: "string" },
    },
    headers: {
      type: "object",
      title: "Headers",
      description: "Header names mapped to template strings.",
      additionalProperties: {
        type: "string",
        "x-refraq-template": { type: "string" },
      },
    },
    body: {
      type: "string",
      title: "Body",
      description:
        "Template rendered to any JSON value. A string is sent as text and any other value as JSON.",
      "x-refraq-template": {
        type: ["object", "array", "string", "number", "boolean", "null"],
      },
    },
  },
};

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
  Range.prototype.getClientRects = () =>
    ({
      length: 0,
      item: () => null,
      [Symbol.iterator]: function* empty() {
        yield* [];
      },
    }) as unknown as () => DOMRectList;
}

function node(config: Record<string, unknown>, nodeType: string, trigger = false): FlowNodeData {
  return {
    nodeType,
    ref: "step",
    name: "Step",
    config,
    onError: "stop",
    retry: null,
    trigger,
    container: null,
    problem: false,
    typeVersion: 1,
  };
}

function renderPanel(
  initial: FlowNodeData,
  schema: SchemaObject | null = { type: "object", properties: {} },
  publishedHookPath: string | null = null,
) {
  const onChange = vi.fn();
  return import("@/features/channels/NodeConfigPanel").then(({ NodeConfigPanel }) => {
    function Panel() {
      const [data, setData] = useState(initial);
      return createElement(NodeConfigPanel, {
        nodeId: "nd_in",
        data,
        spec: null,
        schema,
        editable: true,
        canRun: null,
        scope: { nodes: [], context: { channel: null, run: null, platform: null } },
        publishedHookPath,
        upstream: null,
        result: null,
        onClose: vi.fn(),
        onChange: (nodeId: string, next: FlowNodeData) => {
          onChange(nodeId, next);
          setData(next);
        },
        onRun: vi.fn(),
      });
    }
    render(createElement(MantineProvider, { env: "test" }, createElement(Panel) as ReactNode));
    return onChange;
  });
}

function latestConfig(onChange: ReturnType<typeof vi.fn>): Record<string, unknown> {
  const data = onChange.mock.calls.at(-1)?.[1] as FlowNodeData | undefined;
  if (!data) throw new Error("panel did not report a change");
  return data.config;
}

function pickOption(combobox: HTMLElement, option: string | RegExp) {
  fireEvent.mouseDown(combobox);
  const lists = screen.getAllByRole("listbox", { hidden: true });
  const list = lists.find((item) => within(item).queryByRole("option", { name: option, hidden: true }));
  if (!list) throw new Error("missing option list");
  fireEvent.click(within(list).getByRole("option", { name: option, hidden: true }));
}

const inboundConfig = {
  path: "draft-path",
  credential_id: "",
  response: {
    mode: "immediate",
    status: 202,
    content_type: "text/plain",
    headers: { "X-A": "1" },
    body: { kind: "static", text: "ok" },
  },
};

describe("inbound trigger panel", () => {
  beforeEach(() => {
    stubDomApis();
    vi.mocked(listInboundCredentials).mockResolvedValue({
      items: [PARTNER],
      total: 1,
      limit: 200,
      offset: 0,
    });
  });

  afterEach(() => {
    cleanup();
  });

  it("edits path, allow GET, credential, declared input, event id, dedup window, and in-flight cap", async () => {
    const onChange = await renderPanel(node(inboundConfig, "trigger.inbound", true));

    fireEvent.change(screen.getByRole("textbox", { name: "Path" }), {
      target: { value: "orders" },
    });
    expect(latestConfig(onChange).path).toBe("orders");

    const allowGet = screen.getByRole("switch", { name: "Allow GET" }) as HTMLInputElement;
    expect(allowGet.checked).toBe(false);
    fireEvent.click(allowGet);
    expect(latestConfig(onChange).allow_get).toBe(true);

    await waitFor(() => {
      expect(listInboundCredentials).toHaveBeenCalled();
    });
    pickOption(screen.getByRole("combobox", { name: "Credential" }), /Partner/);
    expect(latestConfig(onChange).credential_id).toBe("icr_1");

    const input = screen.getByRole("group", { name: "Input" });
    fireEvent.click(within(input).getByRole("button", { name: "Add" }));
    fireEvent.change(within(input).getByRole("textbox", { name: "Name" }), {
      target: { value: "sku" },
    });
    pickOption(within(input).getByRole("combobox", { name: "Type" }), "Integer");
    fireEvent.click(within(input).getByRole("switch", { name: "Required" }));
    expect(latestConfig(onChange).input).toEqual([
      { name: "sku", type: "integer", required: true },
    ]);

    pickOption(screen.getByRole("combobox", { name: "Event id from" }), "Header");
    fireEvent.change(screen.getByRole("textbox", { name: "Event id key" }), {
      target: { value: "X-Event-Id" },
    });
    expect(latestConfig(onChange).event_id).toEqual({ from: "header", key: "X-Event-Id" });

    fireEvent.change(screen.getByRole("textbox", { name: "Dedup window" }), {
      target: { value: "120" },
    });
    expect(latestConfig(onChange).dedup_window_sec).toBe(120);
    fireEvent.change(screen.getByRole("textbox", { name: "In-flight cap" }), {
      target: { value: "4" },
    });
    expect(latestConfig(onChange).max_in_flight).toBe(4);
  });

  it("switches response mode without keeping the other mode's fields, and edits the sample request", async () => {
    const onChange = await renderPanel(node(inboundConfig, "trigger.inbound", true));
    const response = screen.getByRole("group", { name: "Response" });

    expect(within(response).getByRole("textbox", { name: "Status" })).toBeTruthy();
    expect(within(response).getByRole("textbox", { name: "Content type" })).toBeTruthy();
    expect(within(response).queryByRole("textbox", { name: "Wait" })).toBeNull();
    const headers = within(response).getByRole("group", { name: "Headers" });
    fireEvent.change(within(headers).getByRole("textbox", { name: "Name" }), {
      target: { value: "X-B" },
    });
    expect(latestConfig(onChange).response).toMatchObject({
      mode: "immediate",
      headers: { "X-B": "1" },
    });

    pickOption(within(response).getByRole("combobox", { name: "Kind" }), "Echo");
    pickOption(within(response).getByRole("combobox", { name: "Echo from" }), "Query");
    fireEvent.change(within(response).getByRole("textbox", { name: "Echo key" }), {
      target: { value: "challenge" },
    });
    expect(latestConfig(onChange).response).toMatchObject({
      body: { kind: "echo", from: "query", key: "challenge" },
    });

    pickOption(within(response).getByRole("combobox", { name: "Mode" }), "Respond node");
    const switched = latestConfig(onChange).response as Record<string, unknown>;
    expect(switched.mode).toBe("respond_node");
    expect(switched).not.toHaveProperty("status");
    expect(switched).not.toHaveProperty("content_type");
    expect(switched).not.toHaveProperty("headers");
    expect(switched).not.toHaveProperty("body");
    expect(within(response).queryByRole("textbox", { name: "Status" })).toBeNull();

    fireEvent.change(within(response).getByRole("textbox", { name: "Wait" }), {
      target: { value: "12" },
    });
    fireEvent.change(within(response).getByRole("textbox", { name: "Fallback status" }), {
      target: { value: "504" },
    });
    fireEvent.change(within(response).getByRole("textbox", { name: "Fallback body" }), {
      target: { value: "later" },
    });
    expect(latestConfig(onChange).response).toEqual({
      mode: "respond_node",
      wait_sec: 12,
      fallback: { status: 504, body: "later" },
    });

    pickOption(within(response).getByRole("combobox", { name: "Mode" }), "Immediate");
    const back = latestConfig(onChange).response as Record<string, unknown>;
    expect(back.mode).toBe("immediate");
    expect(back).not.toHaveProperty("wait_sec");
    expect(back).not.toHaveProperty("fallback");
    expect(back.body).toEqual({ kind: "static", text: "" });

    const sample = screen.getByRole("group", { name: "Sample request" });
    fireEvent.change(within(sample).getByRole("textbox", { name: "Method" }), {
      target: { value: "GET" },
    });
    const query = within(sample).getByRole("group", { name: "Query" });
    fireEvent.click(within(query).getByRole("button", { name: "Add" }));
    fireEvent.change(within(query).getByRole("textbox", { name: "Name" }), {
      target: { value: "echo" },
    });
    fireEvent.change(within(query).getByRole("textbox", { name: "Value" }), {
      target: { value: "1" },
    });
    expect(latestConfig(onChange).sample_request).toEqual({
      method: "GET",
      query: { echo: "1" },
    });
  });

  it("shows and copies the published hook URL, and hides it before that publish", async () => {
    await renderPanel(node(inboundConfig, "trigger.inbound", true));
    expect(screen.queryByRole("button", { name: "Copy public URL" })).toBeNull();
    expect(screen.queryByText(/\/api\/hooks\//)).toBeNull();
    cleanup();

    const onChange = await renderPanel(node(inboundConfig, "trigger.inbound", true), null, "orders");
    const url = "http://localhost:3000/api/hooks/orders";
    expect(screen.getByText(url)).toBeTruthy();
    expect(screen.queryByText("http://localhost:3000/api/hooks/draft-path")).toBeNull();
    fireEvent.click(screen.getByRole("button", { name: "Copy public URL" }));
    expect(copyText).toHaveBeenCalledWith(url);
    expect(onChange).not.toHaveBeenCalled();
  });
});

describe("respond panel", () => {
  beforeEach(stubDomApis);
  afterEach(cleanup);

  it("edits status, content type, header templates, and body, and keeps content type beside a content-type header", async () => {
    const onChange = await renderPanel(
      node(
        {
          status: "201",
          content_type: "application/json",
          headers: { "X-Request-Id": "{{ trigger.output.event_id }}" },
          body: "{\"ok\":true}",
        },
        "action.respond",
      ),
      RESPOND,
    );

    expect(templateText("Status")).toContain("201");
    expect(templateText("Content type")).toContain("application/json");
    expect(templateText("Body")).toContain('{"ok":true}');

    const headers = screen.getByRole("group", { name: "Headers" });
    expect(
      (within(headers).getByRole("textbox", { name: "Name" }) as HTMLInputElement).value,
    ).toBe("X-Request-Id");
    expect(headers.querySelector(".cm-content")?.textContent).toContain(
      "{{ trigger.output.event_id }}",
    );
    fireEvent.change(within(headers).getByRole("textbox", { name: "Name" }), {
      target: { value: "content-type" },
    });
    expect(latestConfig(onChange).headers).toEqual({
      "content-type": "{{ trigger.output.event_id }}",
    });
    expect(latestConfig(onChange).headers).not.toBeInstanceOf(Array);
    expect(templateText("Content type")).toContain("application/json");
  });
});

function templateText(label: string): string {
  const caption = screen.getByText((_content, element) => {
    return element?.tagName === "LABEL" && (element.textContent ?? "").startsWith(label);
  });
  const host = caption.closest(".channel-template-field");
  return host?.querySelector(".cm-content")?.textContent ?? "";
}

function spec(type: string, trigger: boolean, family: string): NodeTypeSpec {
  return {
    type,
    family,
    label: type,
    summary: type,
    description: "",
    trigger,
    container: null,
    inputs: trigger ? [] : [{ port: "main", description: "" }],
    outputs: [{ port: "main", description: "" }],
    config_schema: {},
    permission: null,
  };
}

function renderCanvas(graph: Graph, catalog: NodeTypeSpec[]) {
  return import("@/features/channels/ChannelCanvas").then(({ ChannelCanvas }) => {
    render(
      createElement(
        MantineProvider,
        { env: "test" },
        createElement(ChannelCanvas, {
          graph,
          catalog,
          appearance: "edit",
          mutable: true,
          problems: [],
          onChange: vi.fn(),
        }),
      ),
    );
  });
}

describe("respond palette offer", () => {
  beforeEach(stubDomApis);
  afterEach(cleanup);

  const catalog = [
    spec("trigger.manual", true, "trigger"),
    spec("trigger.inbound", true, "trigger"),
    spec("action.respond", false, "action"),
  ];

  it("keeps Respond out of the palette unless the trigger is inbound in respond_node mode", async () => {
    expect(respondNodeOffered([])).toBe(false);
    expect(
      respondNodeOffered([{ type: "trigger.manual", trigger: true, config: {} }]),
    ).toBe(false);
    expect(
      respondNodeOffered([
        {
          type: "trigger.inbound",
          trigger: true,
          config: { response: { mode: "immediate" } },
        },
      ]),
    ).toBe(false);

    await renderCanvas(EMPTY_GRAPH, catalog);
    fireEvent.click(
      within(await screen.findByRole("toolbar", { name: "channels.canvas.toolbar" })).getByRole(
        "button",
        { name: "channels.canvas.add" },
      ),
    );
    expect(screen.getByRole("option", { name: /trigger.inbound/ })).toBeTruthy();
    expect(screen.queryByRole("option", { name: /action.respond/ })).toBeNull();
    cleanup();

    const inbound = (mode: string): Graph => ({
      nodes: [
        {
          id: "nd_in",
          ref: "in",
          type: "trigger.inbound",
          name: "In",
          position: { x: 40, y: 40 },
          config: {
            path: "orders",
            credential_id: "icr_1",
            response: { mode },
          },
          on_error: "stop",
          retry: null,
        },
      ],
      edges: [],
      settings: EMPTY_GRAPH.settings,
    });

    await renderCanvas(inbound("immediate"), catalog);
    fireEvent.click(
      within(screen.getByRole("toolbar", { name: "channels.canvas.toolbar" })).getByRole("button", {
        name: "channels.canvas.add",
      }),
    );
    expect(screen.queryByRole("option", { name: /action.respond/ })).toBeNull();
    expect(screen.queryByRole("option", { name: /trigger.manual/ })).toBeNull();
    cleanup();

    await renderCanvas(inbound("respond_node"), catalog);
    fireEvent.click(
      within(screen.getByRole("toolbar", { name: "channels.canvas.toolbar" })).getByRole("button", {
        name: "channels.canvas.add",
      }),
    );
    expect(screen.getByRole("option", { name: /action.respond/ })).toBeTruthy();
    expect(screen.queryByRole("option", { name: /trigger.manual/ })).toBeNull();
  });
});
