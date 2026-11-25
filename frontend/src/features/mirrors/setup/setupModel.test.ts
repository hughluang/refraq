import { expect, it } from "vitest";
import en from "@/locales/en-US/common.json";
import zh from "@/locales/zh-CN/common.json";
import {
  acceptedSite, agentInstruction, httpsOrigin, instructionVariables, runtimeConfig, shellCommand,
  type SetupGuide, type SetupSelection, type Translate,
} from "./setupModel";

const patterns = {
  connector_name: "[A-Za-z0-9_-]{1,128}",
  topic_prefix: "[A-Za-z0-9._-]{1,200}",
  bootstrap_servers: "[A-Za-z0-9.-]+:[0-9]{1,5}(?:,[A-Za-z0-9.-]+:[0-9]{1,5})*",
};

function guide(engine: "postgresql" | "oracle"): SetupGuide {
  const scope = engine === "oracle"
    ? { host: "<HOST>", port: "<PORT>", service_name: "<SERVICE_NAME>", tables: ["<QUALIFIED_TABLE>"] }
    : { host: "<HOST>", port: "<PORT>", database: "<DATABASE>", tables: ["<QUALIFIED_TABLE>"], username: "<USERNAME>" };
  return {
    connector_version: "3.7.1.Final",
    compose_service: "api",
    site_inputs: [
      { token: "GATEWAY_ORIGIN", kind: "https_origin" },
      { token: "KAFKA_BOOTSTRAP_SERVERS", kind: "bootstrap_servers" },
      { token: "CONNECTOR_NAME", kind: "connector_name" },
      { token: "TOPIC_PREFIX", kind: "topic_prefix" },
      { token: "CONFIG_DIRECTORY", kind: "directory" },
      { token: "RUNTIME_INSTANCE_ID", kind: "identifier" },
    ],
    steps: ["source", "transport", "target", "gateway", "config", "runtime", "verify"],
    bounds: { poll_interval_seconds_max: 3600, sources_max: 100, timeout_seconds_max: 120, max_response_bytes_max: 1048576, readiness_max_age_seconds: 3600 },
    patterns,
    protected_forbidden_bits: 63,
    target: {
      schema_version: 4, schemas: ["source_mirror", "source_mirror_state"],
      roles: ["refraq_mirror_owner", "refraq_mirror_gateway", "refraq_mirror_applier"],
      login_roles: ["refraq_mirror_gateway", "refraq_mirror_applier"],
      setting: "REFRAQ_MIRROR_TARGET", setting_fields: ["gateway_url", "applier_url", "timeout_ms"],
      driver: "postgresql+psycopg", sslmode: "verify-full",
      url_template: "postgresql+psycopg://<ROLE>:<PASSWORD>@<HOST>/<DATABASE>?sslmode=verify-full",
      bootstrap_env: "MIRROR_ADMIN_URL",
    },
    commands: {
      bootstrap: { argv: ["python", "-m", "backend.metadata.mirrors.bootstrap", "--admin-url-env", "MIRROR_ADMIN_URL"], env: ["MIRROR_ADMIN_URL"], mount: null, host: false },
      directories: { argv: ["install", "-d", "-m", "700", "<CONFIG_DIRECTORY>"], env: [], mount: null, host: true },
      check: { argv: ["python", "-m", "backend.metadata.capture.runtime", "--config-file", "<CONFIG_DIRECTORY>/runtime.json", "--once"], env: [], mount: "<CONFIG_DIRECTORY>", host: false },
      start: { argv: ["python", "-m", "backend.metadata.capture.runtime", "--config-file", "<CONFIG_DIRECTORY>/runtime.json"], env: [], mount: "<CONFIG_DIRECTORY>", host: false },
    },
    runtime_config: { management_database_url_file: "<CONFIG_DIRECTORY>/management_database_url", poll_interval_seconds: "<POLL_INTERVAL_SECONDS>", sources: ["<SOURCE_ENTRY>"] },
    runtime: {
      config_keys: ["management_database_url_file"], check_flag: "--once", recovery_flag: "--dispatch-recovery",
      exit_codes: { ready: 0, blocked: 2 }, fatal_message: "capture_runtime_blocked", fault_codes: ["readiness_unknown_or_failed"],
      readiness_policy_keys: ["required_checks"], credential_file_keys: ["directory"], delivery_settings_keys: ["target"], native_types: ["numeric"],
    },
    gateway: { paths: ["/v1/capture/observations"], optional_paths: ["/v1/capture/diagnostics"], connect_paths: ["/connectors/{name}/status"], required_checks: ["profile_qualified"], signing_trust_keys: ["issuer"], snapshot_observer_keys: ["receipt"] },
    transport: { tls_keys: ["origin"], data_partition: 0 },
    deployment_owned: ["delivery_settings_file", "owner_allocation_file", "snapshot_observers"],
    engines: [{
      code: engine, profile_key: `${engine}_profile`, prerequisites: ["wal_level"], snapshot_prerequisite: "signal_relation",
      source_entry: {
        source_id: "<SOURCE_ID>", connector_name: "<CONNECTOR_NAME>",
        signals_tls: { origin: "<GATEWAY_ORIGIN>" },
        [`${engine}_profile`]: { scope, tls: {} },
      },
    }],
  };
}

const translate: Translate = (key, params = {}) => {
  let text = (en as Record<string, string>)[key] ?? key;
  for (const [name, value] of Object.entries(params)) text = text.replaceAll(`{{${name}}}`, String(value));
  return text;
};

function selection(engine: "postgresql" | "oracle", site: Record<string, string>, access: Record<string, unknown> | null, tables: string[] = ["public.orders"]): SetupSelection {
  return { guide: guide(engine), engine, access, tables, tablesTruncated: false, sourceId: "source-1", sourceName: "Sales", site };
}

it("accepts only an https origin with a host and no path, user, query, or fragment", () => {
  expect(httpsOrigin("https://gateway.internal")).toBe(true);
  expect(httpsOrigin("https://gateway.internal/")).toBe(true);
  expect(httpsOrigin("https://gateway.internal/v1")).toBe(false);
  expect(httpsOrigin("https://user:secret@gateway.internal")).toBe(false);
  expect(httpsOrigin("https://gateway.internal?ready=1")).toBe(false);
  expect(httpsOrigin("https://gateway.internal#top")).toBe(false);
  expect(httpsOrigin("http://gateway.internal")).toBe(false);
});

it("keeps invalid site values out and fills only the same-named access fields", () => {
  const projected = guide("postgresql");
  expect(acceptedSite(projected, { GATEWAY_ORIGIN: " http://no ", KAFKA_BOOTSTRAP_SERVERS: "kafka:9092" })).toEqual({ KAFKA_BOOTSTRAP_SERVERS: "kafka:9092" });
  const config = runtimeConfig(selection("postgresql", { GATEWAY_ORIGIN: "https://gateway.internal" }, {
    host: "db.example", port: 5432, database: "app", username: "secretuser", password: "secret",
  }));
  const entry = config.sources[0] as { signals_tls: { origin: string }; postgresql_profile: { scope: Record<string, unknown> } };
  expect(entry.signals_tls.origin).toBe("https://gateway.internal");
  expect(entry.postgresql_profile.scope).toMatchObject({ host: "db.example", port: 5432, database: "app", tables: ["public.orders"] });
  expect(JSON.stringify(config)).not.toContain("secretuser");
  expect(entry.postgresql_profile.scope.username).toBe("<USERNAME>");
});

it("fills an Oracle service name and leaves unresolved placeholders", () => {
  const built = instructionVariables(translate, selection("oracle", {}, { host: "db.example", port: 1521, service_name: "ORCL", username: "secretuser" }, ["APP.ORDERS"]));
  const entry = built.config.sources[0] as { oracle_profile: { scope: Record<string, unknown> } };
  expect(entry.oracle_profile.scope.service_name).toBe("ORCL");
  expect(entry.oracle_profile.scope.tables).toEqual(["APP.ORDERS"]);
  expect(built.missing).toContain("<PASSWORD>");
  expect(built.missing).toContain("<GATEWAY_ORIGIN>");
  expect(JSON.stringify(built.config)).not.toContain("secretuser");
});

it("renders the bootstrap command and the hard rules with the selected Source", () => {
  const command = shellCommand("api", guide("postgresql").commands.bootstrap, {});
  expect(command).toBe("docker compose run --rm --no-deps -e MIRROR_ADMIN_URL api python -m backend.metadata.mirrors.bootstrap --admin-url-env MIRROR_ADMIN_URL");
  const text = agentInstruction(translate, selection("postgresql", { TOPIC_PREFIX: "refraq.capture" }, { host: "db.example", port: 5432, database: "app" }));
  expect(text).toContain("source-1");
  expect(text).toContain("Do not put secrets in the chat");
  expect(text).toContain("Do not assume a default URL");
  expect(text).toContain("Do not invent production limits");
  expect(text).toContain("database administrator has approved");
  expect(text).toContain(command);
});

it("keeps deploy-and-connect copy aligned and only interpolates known facts", () => {
  const english = en as Record<string, string>;
  const chinese = zh as Record<string, string>;
  const chosen = (catalog: Record<string, string>) => Object.keys(catalog).filter(key => key.startsWith("mirrorSetup.") || key === "fleet.setup").sort();
  const enKeys = chosen(english);
  const tokens = (text: string) => [...text.matchAll(/\{\{(\w+)\}\}/g)].map(match => match[1]);
  expect(chosen(chinese)).toEqual(enKeys);
  expect(enKeys).toContain("fleet.setup");
  const known = new Set(Object.keys(instructionVariables(translate, selection("postgresql", {}, null)).vars));
  known.add("tables");
  for (const key of enKeys) {
    expect(english[key]).not.toMatch(/[\u4e00-\u9fff]/);
    expect(english[key]).not.toContain("\n");
    expect(tokens(english[key])).toEqual(tokens(chinese[key]));
    for (const token of tokens(english[key])) expect(known.has(token)).toBe(true);
  }
});
