/** @vitest-environment jsdom */

import { MantineProvider } from "@mantine/core";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { useState } from "react";
import { afterEach, beforeAll, expect, it, vi } from "vitest";

import { defaultsFromSchema, SpecTree, validateSourceAccess } from "./SpecTree";
import type { ConnectorSpec, SourceAccess } from "./types";
import en from "@/locales/en-US/common.json";

function t(key: string, values?: Record<string, unknown>) {
  return ((en as Record<string, string>)[key] ?? key).replace(
    /\{\{(\w+)\}\}/g, (_, name: string) => String(values?.[name] ?? ""),
  );
}

vi.mock("@refinedev/core", () => ({ useTranslate: () => t }));

beforeAll(() => {
  Object.defineProperty(window, "matchMedia", {
    configurable: true,
    value: () => ({ matches: false, addEventListener() {}, removeEventListener() {} }),
  });
  Object.defineProperty(document, "fonts", { configurable: true, value: new EventTarget() });
  vi.stubGlobal("ResizeObserver", class { observe() {} unobserve() {} disconnect() {} });
});

afterEach(cleanup);

const schema: ConnectorSpec = {
  type: "object",
  required: ["host", "port", "username", "password", "database", "ssl_mode"],
  properties: {
    host: { type: "string", minLength: 1, maxLength: 10 },
    port: { type: "integer", default: 5432, minimum: 1, maximum: 65535 },
    username: { type: "string", minLength: 1 },
    password: { type: "string", minLength: 1, "x-secret": true },
    database: { type: "string", minLength: 1 },
    ssl_mode: { type: "string", enum: ["disable", "require", "verify-full"], default: "require" },
    ssl_client_key: { type: "string", "x-secret": true },
    extra: {
      type: "object", additionalProperties: { type: "string", maxLength: 8 },
      propertyNames: { type: "string", minLength: 1, maxLength: 16 }, default: {},
    },
  },
};

it("returns addressable errors for the submitted engine without echoing entered values", () => {
  const value = {
    ...defaultsFromSchema(schema), host: "too-long-host", port: 65536, username: "reader",
    password: " ", ssl_mode: "unsupported", extra: { option: "too-long-value" },
  };
  const errors = validateSourceAccess(schema, value, t);
  expect(Object.keys(errors).sort()).toEqual([
    "access.database", "access.extra.option", "access.host", "access.port", "access.ssl_mode",
  ]);
  expect(Object.values(errors).join(" ")).not.toMatch(/too-long|unsupported/);
  expect(validateSourceAccess(schema, {
    ...value, host: "localhost", port: 5432, database: "reports", ssl_mode: "require", extra: {},
  }, t)).toEqual({});
});

function Editor({ spec, initial, editable = true }: { spec: ConnectorSpec; initial?: SourceAccess; editable?: boolean }) {
  const [value, setValue] = useState(initial ?? defaultsFromSchema(spec));
  return (
    <MantineProvider env="test">
      <SpecTree schema={spec} value={value} onChange={setValue} editable={editable} />
    </MantineProvider>
  );
}

it("organizes the connection around the engine's available settings and labels required inputs", () => {
  const mysql = {
    ...schema,
    properties: {
      host: schema.properties!.host,
      username: schema.properties!.username,
      database: schema.properties!.database,
      ssl_mode: { type: "string", enum: ["disable"], default: "disable" },
      extra: { type: "object", additionalProperties: false },
    },
  };
  render(<Editor spec={mysql} />);
  expect(screen.getByRole("heading", { name: "Server and scope" })).toBeTruthy();
  expect(screen.getByLabelText(/^Host/).getAttribute("name")).toBe("access.host");
  expect(screen.getByLabelText(/^Database/).hasAttribute("required")).toBe(true);
  expect(screen.getByRole("heading", { name: "Authentication" })).toBeTruthy();
  expect(screen.getByText("Disabled")).toBeTruthy();
  expect(screen.queryByRole("combobox")).toBeNull();
  expect(screen.queryByText("Advanced settings")).toBeNull();
  expect(screen.queryByText("Extra property name")).toBeNull();
});

it("opens advanced settings at the editable TLS control when validation needs it", () => {
  const value = { ...defaultsFromSchema(schema), ssl_mode: "invalid" };
  render(
    <MantineProvider env="test">
      <SpecTree schema={schema} value={value} onChange={() => {}} editable errors={{ "access.ssl_mode": "Choose a TLS mode." }} />
    </MantineProvider>,
  );
  expect(screen.getByText("Advanced settings").closest("details")?.open).toBe(true);
  expect(document.activeElement).toBe(screen.getByLabelText(/^TLS mode/, { selector: "input" }));
});

it("keeps multiline PEM and driver options through disclosure toggles and redacts secrets on display", () => {
  const { unmount } = render(<Editor spec={schema} />);
  const summary = screen.getByText("Advanced settings").closest("summary")!;
  fireEvent.click(summary);
  const pem = "example-line-one\nexample-line-two";
  fireEvent.change(screen.getByLabelText("Client private key (PEM)"), { target: { value: pem } });
  fireEvent.change(screen.getByLabelText("Option name"), { target: { value: "app.name" } });
  fireEvent.click(screen.getByRole("button", { name: "Add option" }));
  fireEvent.change(screen.getByLabelText("app.name"), { target: { value: "reports" } });
  fireEvent.click(summary);
  expect(summary.textContent).toContain("Certificate material configured");
  expect(summary.textContent).toContain("Driver options (1)");
  fireEvent.click(summary);
  expect((screen.getByLabelText("Client private key (PEM)") as HTMLTextAreaElement).value).toBe(pem);
  expect((screen.getByLabelText("app.name") as HTMLInputElement).value).toBe("reports");
  fireEvent.click(screen.getByRole("button", { name: "Remove app.name" }));
  expect(screen.queryByLabelText("app.name")).toBeNull();
  unmount();
  render(<Editor spec={schema} initial={{ ...defaultsFromSchema(schema), password: "password-example", ssl_client_key: pem }} editable={false} />);
  fireEvent.click(screen.getByText("Advanced settings").closest("summary")!);
  expect(screen.getAllByText("Hidden")).toHaveLength(2);
  expect(document.body.textContent).not.toContain("example-line");
  expect(document.body.textContent).not.toContain("password-example");
});

it.each([
  { scope: "service_name", label: "Service name", secondary: "owner", secondaryLabel: "Owner", defaultValue: "", port: 1521 },
  { scope: "database", label: "Database", secondary: "schema", secondaryLabel: "Schema", defaultValue: "dbo", port: 1433 },
])("shows $label and $secondaryLabel with engine-specific defaults", ({ scope, label, secondary, secondaryLabel, defaultValue, port }) => {
  const spec = {
    properties: {
      [scope]: { type: "string" },
      [secondary]: { type: "string", default: defaultValue },
      port: { type: "integer", default: port },
    },
    required: [scope, secondary, "port"],
  };
  render(<Editor spec={spec} />);
  expect((screen.getByRole("textbox", { name: new RegExp(label) }) as HTMLInputElement).name).toBe(`access.${scope}`);
  expect((screen.getByRole("textbox", { name: new RegExp(secondaryLabel) }) as HTMLInputElement).value).toBe(defaultValue);
  expect((screen.getByLabelText(/^Port/) as HTMLInputElement).value).toBe(String(port));
});
