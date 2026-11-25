import type { SetupStep } from "./setupLinks";

export type SetupCommand = {
  argv: string[];
  env: string[];
  mount: string | null;
  host: boolean;
};

export type SetupInputKind = "https_origin" | "bootstrap_servers" | "identifier" | "connector_name" | "topic_prefix" | "directory";

export type SetupGuide = {
  connector_version: string;
  compose_service: string;
  site_inputs: { token: string; kind: SetupInputKind }[];
  steps: string[];
  bounds: {
    poll_interval_seconds_max: number;
    sources_max: number;
    timeout_seconds_max: number;
    max_response_bytes_max: number;
    readiness_max_age_seconds: number;
  };
  patterns: { connector_name: string; topic_prefix: string; bootstrap_servers: string };
  protected_forbidden_bits: number;
  target: {
    schema_version: number;
    schemas: string[];
    roles: string[];
    login_roles: string[];
    setting: string;
    setting_fields: string[];
    driver: string;
    sslmode: string;
    url_template: string;
    bootstrap_env: string;
  };
  commands: Record<string, SetupCommand>;
  runtime_config: Record<string, unknown>;
  runtime: {
    config_keys: string[];
    check_flag: string;
    recovery_flag: string;
    exit_codes: { ready: number; blocked: number };
    fatal_message: string;
    fault_codes: string[];
    readiness_policy_keys: string[];
    credential_file_keys: string[];
    delivery_settings_keys: string[];
    native_types: string[];
  };
  gateway: {
    paths: string[];
    optional_paths: string[];
    connect_paths: string[];
    required_checks: string[];
    signing_trust_keys: string[];
    snapshot_observer_keys: string[];
  };
  transport: { tls_keys: string[]; data_partition: number };
  deployment_owned: string[];
  engines: {
    code: string;
    profile_key: string;
    prerequisites: string[];
    snapshot_prerequisite: string;
    source_entry: Record<string, unknown>;
  }[];
};

export const PROMPT_FACT_KEYS = [
  "mirrorSetup.prompt.goal",
  "mirrorSetup.prompt.boundary",
  "mirrorSetup.prompt.source",
  "mirrorSetup.prompt.endpoint",
  "mirrorSetup.prompt.tables",
  "mirrorSetup.prompt.versions",
  "mirrorSetup.prompt.site",
  "mirrorSetup.prompt.missing",
] as const;

export const PROMPT_RULE_KEYS = [
  "mirrorSetup.prompt.rulesTitle",
  "mirrorSetup.prompt.ruleSecrets",
  "mirrorSetup.prompt.ruleNoDefaultUrl",
  "mirrorSetup.prompt.ruleNoLimits",
  "mirrorSetup.prompt.ruleNoDdl",
  "mirrorSetup.prompt.acceptanceTitle",
  "mirrorSetup.prompt.acceptanceRuntime",
  "mirrorSetup.prompt.acceptanceConsole",
] as const;

const TOKEN = /<[A-Z][A-Z0-9_]*>/g;
const ACCESS_KEYS = new Set(["host", "port", "database", "service_name"]);

export type Translate = (key: string, vars?: Record<string, unknown>) => string;

export type SetupSelection = {
  guide: SetupGuide;
  engine: string | null;
  access: Record<string, unknown> | null;
  tables: string[];
  tablesTruncated: boolean;
  sourceId: string;
  sourceName: string;
  site: Record<string, string>;
};

export function httpsOrigin(value: string) {
  try {
    const url = new URL(value);
    return url.protocol === "https:" && url.hostname !== "" && url.username === "" && url.password === ""
      && (url.pathname === "" || url.pathname === "/") && url.search === "" && url.hash === "";
  } catch {
    return false;
  }
}

export function acceptSiteValue(kind: SetupInputKind, value: string, patterns: SetupGuide["patterns"]) {
  const trimmed = value.trim();
  if (!trimmed) return false;
  if (kind === "https_origin") return httpsOrigin(trimmed);
  if (kind === "bootstrap_servers") return new RegExp(`^(?:${patterns.bootstrap_servers})$`).test(trimmed);
  if (kind === "connector_name") return new RegExp(`^(?:${patterns.connector_name})$`).test(trimmed);
  if (kind === "topic_prefix") return new RegExp(`^(?:${patterns.topic_prefix})$`).test(trimmed);
  return true;
}

export function acceptedSite(guide: SetupGuide, values: Record<string, string>) {
  const site: Record<string, string> = {};
  for (const input of guide.site_inputs) {
    const value = values[input.token]?.trim() ?? "";
    if (acceptSiteValue(input.kind, value, guide.patterns)) site[input.token] = value;
  }
  return site;
}

export function substitute<T>(value: T, site: Record<string, string>): T {
  if (typeof value === "string") {
    return value.replace(TOKEN, token => site[token.slice(1, -1)] || token) as T;
  }
  if (Array.isArray(value)) return value.map(item => substitute(item, site)) as T;
  if (value && typeof value === "object") {
    return Object.fromEntries(Object.entries(value).map(([key, item]) => [key, substitute(item, site)])) as T;
  }
  return value;
}

function overlay(value: unknown, access: Record<string, unknown> | null, tables: string[], sourceId: string): unknown {
  if (Array.isArray(value)) return value.map(item => overlay(item, access, tables, sourceId));
  if (!value || typeof value !== "object") return value;
  const result: Record<string, unknown> = {};
  for (const [key, item] of Object.entries(value)) {
    if (key === "source_id" && sourceId) result[key] = sourceId;
    else if (access && ACCESS_KEYS.has(key) && (typeof access[key] === "string" || typeof access[key] === "number") && access[key] !== "") result[key] = access[key];
    else if (key === "tables" && tables.length > 0) result[key] = tables;
    else result[key] = overlay(item, access, tables, sourceId);
  }
  return result;
}

export function runtimeConfig(selection: SetupSelection) {
  const engine = selection.guide.engines.find(item => item.code === selection.engine);
  const config = substitute(selection.guide.runtime_config, selection.site);
  const entry = engine
    ? overlay(substitute(engine.source_entry, selection.site), selection.access, selection.tables, selection.sourceId)
    : null;
  return { ...config, sources: entry ? [entry] : [] };
}

export function targetSetting(guide: SetupGuide) {
  const [gateway, applier] = guide.target.login_roles;
  const fields: Record<string, string> = {};
  for (const field of guide.target.setting_fields) {
    if (field.endsWith("gateway_url")) fields[field] = guide.target.url_template.replace("<ROLE>", gateway);
    else if (field === "applier_url") fields[field] = guide.target.url_template.replace("<ROLE>", applier);
    else fields[field] = `<${field.toUpperCase()}>`;
  }
  return JSON.stringify(fields, null, 2);
}

function quote(token: string) {
  if (/^[A-Za-z0-9_./:=@<>+-]+$/.test(token)) return token;
  return `'${token.replaceAll("'", `'\\''`)}'`;
}

export function shellCommand(service: string, command: SetupCommand, site: Record<string, string>) {
  const argv = (substitute(command.argv, site) as string[]).map(quote);
  if (command.host) return argv.join(" ");
  const env = command.env.map(name => `-e ${quote(name)}`).join(" ");
  const mounted = command.mount ? substitute(command.mount, site) as string : "";
  const mount = mounted ? `-v ${quote(mounted)}:${quote(mounted)}:ro` : "";
  return ["docker compose run --rm --no-deps", env, mount, service, ...argv].filter(Boolean).join(" ");
}

export function collectPlaceholders(value: unknown) {
  const found = new Set<string>();
  const visit = (item: unknown) => {
    if (typeof item === "string") {
      for (const match of item.matchAll(TOKEN)) found.add(match[0]);
    } else if (Array.isArray(item)) item.forEach(visit);
    else if (item && typeof item === "object") Object.values(item).forEach(visit);
  };
  visit(value);
  return [...found].sort();
}

export function endpointText(access: Record<string, unknown> | null) {
  if (!access || (typeof access.host !== "string" && typeof access.host !== "number")) return "";
  const port = typeof access.port === "number" || typeof access.port === "string" ? `:${access.port}` : "";
  const name = typeof access.database === "string" ? access.database
    : typeof access.service_name === "string" ? access.service_name : "";
  return `${access.host}${port}${name ? `/${name}` : ""}`;
}

export function instructionVariables(t: Translate, selection: SetupSelection) {
  const guide = selection.guide;
  const config = runtimeConfig(selection);
  const setting = targetSetting(guide);
  const commands = Object.fromEntries(Object.entries(guide.commands).map(([name, command]) => [name, shellCommand(guide.compose_service, command, selection.site)]));
  const missing = collectPlaceholders({ config, setting, commands });
  const siteValues = Object.entries(selection.site).map(([key, value]) => `${key}=${value}`).join(", ");
  return {
    vars: {
      source: selection.sourceName || t("mirrorSetup.noSource"),
      sourceId: selection.sourceId || t("mirrorSetup.noSource"),
      engine: selection.engine || t("mirrorSetup.noSource"),
      endpoint: endpointText(selection.access) || t("mirrorSetup.endpointUnknown"),
      tables: selection.tablesTruncated
        ? t("mirrorSetup.tablesTruncated", { tables: selection.tables.join(", ") })
        : selection.tables.join(", ") || t("mirrorSetup.tablesEmpty"),
      connectorVersion: guide.connector_version,
      schemaVersion: guide.target.schema_version,
      schemas: guide.target.schemas.join(", "),
      roles: guide.target.roles.join(", "),
      loginRoles: guide.target.login_roles.join(", "),
      setting: guide.target.setting,
      bootstrapEnv: guide.target.bootstrap_env,
      sslmode: guide.target.sslmode,
      topicPrefix: selection.site.TOPIC_PREFIX || "<TOPIC_PREFIX>",
      partition: guide.transport.data_partition,
      paths: guide.gateway.paths.join(", "),
      optionalPath: guide.gateway.optional_paths[0] ?? "",
      checks: guide.gateway.required_checks.join(", "),
      maxAge: guide.bounds.readiness_max_age_seconds,
      pollMax: guide.bounds.poll_interval_seconds_max,
      sourcesMax: guide.bounds.sources_max,
      timeoutMax: guide.bounds.timeout_seconds_max,
      responseMax: guide.bounds.max_response_bytes_max,
      exitReady: guide.runtime.exit_codes.ready,
      exitBlocked: guide.runtime.exit_codes.blocked,
      fatalMessage: guide.runtime.fatal_message,
      nativeTypes: guide.runtime.native_types.join(", "),
      siteValues: siteValues || t("mirrorSetup.noneMissing"),
      missing: missing.join(", ") || t("mirrorSetup.noneMissing"),
    },
    config,
    setting,
    commands,
    missing,
  };
}

export function agentInstruction(t: Translate, selection: SetupSelection) {
  const { vars, config, setting, commands } = instructionVariables(t, selection);
  const engine = selection.guide.engines.find(item => item.code === selection.engine);
  const lines = PROMPT_FACT_KEYS.map(key => t(key, vars));
  for (const step of selection.guide.steps) {
    lines.push(t(`mirrorSetup.step.${step}.title`, vars), t(`mirrorSetup.step.${step}.body`, vars));
    if (step === "source" && engine) {
      for (const name of [...engine.prerequisites, engine.snapshot_prerequisite]) {
        lines.push(t(`mirrorSetup.prerequisite.${engine.code}.${name}`));
      }
    }
    if (step === "target") lines.push(commands.bootstrap, setting);
    if (step === "config") {
      lines.push(commands.directories);
      for (const key of selection.guide.deployment_owned) lines.push(t(`mirrorSetup.owned.${key}`));
    }
    if (step === "runtime") {
      lines.push(commands.check, commands.start);
      for (const code of selection.guide.runtime.fault_codes) lines.push(`${code}: ${t(`mirrorSetup.fault.${code}`)}`);
    }
  }
  lines.push(...PROMPT_RULE_KEYS.map(key => t(key, vars)));
  lines.push(t("mirrorSetup.config.title"), JSON.stringify(config, null, 2));
  return lines.filter(line => line !== "").join("\n");
}

export function stepCommand(step: SetupStep, commands: Record<string, string>, setting: string) {
  if (step === "target") return [commands.bootstrap, setting].filter(Boolean).join("\n\n");
  if (step === "config") return commands.directories ?? "";
  if (step === "runtime") return [commands.check, commands.start].filter(Boolean).join("\n");
  return "";
}
