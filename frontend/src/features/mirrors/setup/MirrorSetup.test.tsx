/** @vitest-environment jsdom */
import { createElement, forwardRef, type ComponentProps, type ReactNode } from "react";
import { MantineProvider } from "@mantine/core";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeAll, expect, it, vi } from "vitest";
import en from "@/locales/en-US/common.json";
import { MirrorSetup } from "./MirrorSetup";
import type { SetupGuide } from "./setupModel";

const location = vi.hoisted(() => ({ pathname: "/console/mirrors/setup", search: "source_id=source-1&step=target" }));
const state = vi.hoisted(() => ({
  guide: vi.fn(),
  source: vi.fn(),
  inventory: vi.fn(),
  push: vi.fn(),
  open: vi.fn(),
}));

vi.mock("@refinedev/core", () => ({
  useTranslate: () => (key: string, params: Record<string, unknown> = {}) => {
    let text = (en as Record<string, string>)[key] ?? key;
    for (const [name, value] of Object.entries(params)) text = text.replaceAll(`{{${name}}}`, String(value));
    return text;
  },
  useCan: () => ({ data: { can: true } }),
  useNotification: () => ({ open: state.open }),
}));
vi.mock("@/components/navigation/useConsoleNavigation", () => ({
  useConsoleLocation: () => ({ pathname: location.pathname, search: new URLSearchParams(location.search), href: `${location.pathname}?${location.search}` }),
  useConsoleNavigation: () => ({ push: state.push, replace: vi.fn() }),
}));
vi.mock("@/components/navigation/ConsoleLink", () => ({ ConsoleLink: forwardRef<HTMLAnchorElement, ComponentProps<"a">>((props, ref) => createElement("a", { ...props, ref })) }));
vi.mock("@/components/layout/PageChrome", () => ({
  PageChrome: ({ title, description, tabs, children }: { title: string; description?: string; tabs?: ReactNode; children?: ReactNode }) =>
    createElement("section", null, createElement("h1", null, title), description, tabs, children),
}));
vi.mock("../api", () => ({ getMirrorSetup: state.guide, listMirrorInventory: state.inventory, listFleetSources: vi.fn() }));
vi.mock("@/features/sources/api/sources", () => ({ getSource: state.source, listSources: vi.fn().mockResolvedValue({ items: [], total: 0 }) }));

const guide: SetupGuide = {
  connector_version: "3.7.1.Final",
  compose_service: "api",
  site_inputs: [
    { token: "GATEWAY_ORIGIN", kind: "https_origin" },
    { token: "CONFIG_DIRECTORY", kind: "directory" },
  ],
  steps: ["source", "transport", "target", "gateway", "config", "runtime", "verify"],
  bounds: { poll_interval_seconds_max: 3600, sources_max: 100, timeout_seconds_max: 120, max_response_bytes_max: 1048576, readiness_max_age_seconds: 3600 },
  patterns: { connector_name: "[A-Za-z0-9_-]{1,128}", topic_prefix: "[A-Za-z0-9._-]{1,200}", bootstrap_servers: "[A-Za-z0-9.-]+:[0-9]{1,5}" },
  protected_forbidden_bits: 63,
  target: {
    schema_version: 4, schemas: ["source_mirror"], roles: ["refraq_mirror_owner"], login_roles: ["refraq_mirror_gateway", "refraq_mirror_applier"],
    setting: "REFRAQ_MIRROR_TARGET", setting_fields: ["gateway_url", "applier_url"], driver: "postgresql+psycopg", sslmode: "verify-full",
    url_template: "postgresql+psycopg://<ROLE>:<PASSWORD>@<HOST>/<DATABASE>?sslmode=verify-full", bootstrap_env: "MIRROR_ADMIN_URL",
  },
  commands: {
    bootstrap: { argv: ["python", "-m", "backend.metadata.mirrors.bootstrap", "--admin-url-env", "MIRROR_ADMIN_URL"], env: ["MIRROR_ADMIN_URL"], mount: null, host: false },
    directories: { argv: ["install", "-d", "-m", "700", "<CONFIG_DIRECTORY>"], env: [], mount: null, host: true },
    check: { argv: ["python", "-m", "backend.metadata.capture.runtime", "--once"], env: [], mount: "<CONFIG_DIRECTORY>", host: false },
    start: { argv: ["python", "-m", "backend.metadata.capture.runtime"], env: [], mount: "<CONFIG_DIRECTORY>", host: false },
  },
  runtime_config: { poll_interval_seconds: "<POLL_INTERVAL_SECONDS>", sources: ["<SOURCE_ENTRY>"] },
  runtime: {
    config_keys: ["sources"], check_flag: "--once", recovery_flag: "--dispatch-recovery", exit_codes: { ready: 0, blocked: 2 },
    fatal_message: "capture_runtime_blocked", fault_codes: ["readiness_unknown_or_failed"], readiness_policy_keys: [], credential_file_keys: [],
    delivery_settings_keys: [], native_types: ["numeric"],
  },
  gateway: { paths: ["/v1/capture/observations"], optional_paths: ["/v1/capture/diagnostics"], connect_paths: [], required_checks: ["profile_qualified"], signing_trust_keys: [], snapshot_observer_keys: [] },
  transport: { tls_keys: ["origin"], data_partition: 0 },
  deployment_owned: ["delivery_settings_file"],
  engines: [{
    code: "postgresql", profile_key: "postgresql_profile", prerequisites: ["wal_level"], snapshot_prerequisite: "signal_relation",
    source_entry: {
      source_id: "<SOURCE_ID>",
      signals_tls: { origin: "<GATEWAY_ORIGIN>" },
      postgresql_profile: { scope: { host: "<HOST>", port: "<PORT>", database: "<DATABASE>", tables: ["<QUALIFIED_TABLE>"], username: "<USERNAME>" }, tls: {} },
    },
  }],
};

beforeAll(() => {
  window.matchMedia = vi.fn().mockImplementation(query => ({ matches: false, media: query, addEventListener: vi.fn(), removeEventListener: vi.fn(), addListener: vi.fn(), removeListener: vi.fn() }));
  global.ResizeObserver = class { observe() {} unobserve() {} disconnect() {} };
});
afterEach(() => { cleanup(); vi.clearAllMocks(); });

function renderSetup() {
  state.guide.mockResolvedValue(guide);
  state.source.mockResolvedValue({ source: { id: "source-1", name: "Sales", engine: "postgresql", access: { host: "db.example", port: 5432, database: "app", username: "secretuser" } } });
  state.inventory.mockResolvedValue({ items: [{ qualified_table: "public.orders" }], total: 1 });
  return render(createElement(MirrorSetup), { wrapper: ({ children }: { children: ReactNode }) => createElement(MantineProvider, null, children) });
}

it("fills the selected Source and keeps an invalid gateway origin as a placeholder", async () => {
  renderSetup();
  expect((await screen.findAllByText(/db\.example:5432\/app/)).length).toBeGreaterThan(0);
  expect(screen.getAllByText(/public\.orders/).length).toBeGreaterThan(0);
  expect(document.body.textContent).not.toContain("secretuser");
  expect(screen.queryByRole("button", { name: "Find Source" })).toBeNull();
  const target = document.getElementById("setup-target") as HTMLDetailsElement;
  expect(target.open).toBe(true);
  expect(target.textContent).toContain("docker compose run --rm --no-deps -e MIRROR_ADMIN_URL api");
  expect(document.getElementById("setup-source")?.hasAttribute("open")).toBe(false);

  const origin = screen.getByLabelText("Signed evidence gateway origin");
  fireEvent.change(origin, { target: { value: "http://gateway.internal" } });
  expect(screen.getByText("Use an https origin with a host and no user, path, query, or fragment.")).toBeTruthy();
  expect(document.body.textContent).toContain("<GATEWAY_ORIGIN>");

  fireEvent.change(origin, { target: { value: "https://gateway.internal" } });
  await waitFor(() => expect(document.body.textContent).not.toContain("<GATEWAY_ORIGIN>"));
  expect(document.body.textContent).toContain("https://gateway.internal");
  expect(screen.queryByText("Use an https origin with a host and no user, path, query, or fragment.")).toBeNull();
});
