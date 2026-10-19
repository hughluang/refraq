export const TONES = [
  "neutral",
  "info",
  "running",
  "success",
  "warning",
  "danger",
] as const;

export type Tone = (typeof TONES)[number];

export type StatusTone = {
  tone: Tone;
  labelKey: string;
};

/** Mantine palette name for Badge and other `color` props. Matches the tone variables. */
export const TONE_MANTINE_COLOR: Record<Tone, string> = {
  neutral: "gray",
  info: "blue",
  running: "cyan",
  success: "green",
  warning: "yellow",
  danger: "red",
};

export function toneMantineColor(tone: Tone): string {
  return TONE_MANTINE_COLOR[tone];
}

/** Solid tone color custom property, for borders and marks outside Badge. */
export function toneVariable(tone: Tone): string {
  return `var(--refraq-tone-${tone})`;
}

const UNKNOWN_STATUS: StatusTone = {
  tone: "neutral",
  labelKey: "status.unknown",
};

function fromTable(table: Record<string, StatusTone>, value: string): StatusTone {
  return table[value] ?? UNKNOWN_STATUS;
}

const JOB_STATUS: Record<string, StatusTone> = {
  queued: { tone: "info", labelKey: "status.job.queued" },
  running: { tone: "running", labelKey: "status.job.running" },
  succeeded: { tone: "success", labelKey: "status.job.succeeded" },
  failed: { tone: "danger", labelKey: "status.job.failed" },
  cancelled: { tone: "neutral", labelKey: "status.job.cancelled" },
};

/** Job status and Channel Run status share this enum. */
export function presentJobStatus(status: string): StatusTone {
  return fromTable(JOB_STATUS, status);
}

const NODE_STATUS: Record<string, StatusTone> = {
  waiting: { tone: "neutral", labelKey: "channels.run.waiting" },
  running: { tone: "running", labelKey: "channels.editor.status.running" },
  succeeded: { tone: "success", labelKey: "channels.editor.status.succeeded" },
  failed: { tone: "danger", labelKey: "channels.editor.status.failed" },
  skipped: { tone: "neutral", labelKey: "channels.editor.status.skipped" },
  cancelled: { tone: "neutral", labelKey: "channels.editor.status.cancelled" },
  dead: { tone: "neutral", labelKey: "channels.run.notRun" },
};

/** Channel node execution status and canvas run phase. */
export function presentNodeStatus(status: string): StatusTone {
  return fromTable(NODE_STATUS, status);
}

const ENTITY_STATUS: Record<string, StatusTone> = {
  not_serving: { tone: "neutral", labelKey: "entities.status.notServing" },
  serving: { tone: "success", labelKey: "entities.status.serving" },
  deprecated: { tone: "danger", labelKey: "entities.status.deprecated" },
};

export function presentEntityStatus(status: string): StatusTone {
  return fromTable(ENTITY_STATUS, status);
}

const PUBLISH_STATUS: Record<string, StatusTone> = {
  unpublished: { tone: "neutral", labelKey: "entities.status.unpublished" },
  publishing: { tone: "running", labelKey: "entities.status.publishing" },
  published: { tone: "success", labelKey: "entities.status.published" },
};

export function presentPublishStatus(status: string): StatusTone {
  return fromTable(PUBLISH_STATUS, status);
}

export function presentDictionaryStatus(deprecated: boolean): StatusTone {
  return deprecated
    ? { tone: "danger", labelKey: "dictionaries.status.deprecated" }
    : { tone: "success", labelKey: "dictionaries.status.available" };
}

const TOKEN_STATUS: Record<string, StatusTone> = {
  active: { tone: "success", labelKey: "tokens.status.active" },
  expired: { tone: "neutral", labelKey: "tokens.status.expired" },
  deactivated: { tone: "warning", labelKey: "tokens.status.deactivated" },
};

export function presentTokenStatus(status: string): StatusTone {
  return fromTable(TOKEN_STATUS, status);
}

const SOURCE_STATUS: Record<string, StatusTone> = {
  active: { tone: "success", labelKey: "sources.status.active" },
  disabled: { tone: "neutral", labelKey: "sources.status.disabled" },
};

export function presentSourceStatus(status: string): StatusTone {
  return fromTable(SOURCE_STATUS, status);
}

const STRUCTURE_DIFF_CLASS: Record<string, StatusTone> = {
  breaking: { tone: "danger", labelKey: "structureDiffs.class.breaking" },
  non_breaking: { tone: "info", labelKey: "structureDiffs.class.non_breaking" },
  unchanged: { tone: "neutral", labelKey: "structureDiffs.class.unchanged" },
};

export function presentStructureDiffClass(value: string): StatusTone {
  return fromTable(STRUCTURE_DIFF_CLASS, value);
}

export function presentChannelActive(active: boolean): StatusTone {
  return active
    ? { tone: "success", labelKey: "channels.status.active" }
    : { tone: "neutral", labelKey: "channels.status.inactive" };
}

export function presentCatalogPresence(present: boolean): StatusTone {
  return present
    ? { tone: "success", labelKey: "catalog.fields.presentValue" }
    : { tone: "neutral", labelKey: "catalog.fields.absentValue" };
}

export function presentCatalogSemantics(ready: boolean): StatusTone {
  return ready
    ? { tone: "success", labelKey: "catalog.semantics.ready" }
    : { tone: "neutral", labelKey: "catalog.semantics.notReady" };
}

export function presentIdentityProviderEnabled(enabled: boolean): StatusTone {
  return enabled
    ? { tone: "success", labelKey: "identityProviders.status.enabled" }
    : { tone: "neutral", labelKey: "identityProviders.status.disabled" };
}

export function presentModelServiceUse(inUse: boolean): StatusTone {
  return inUse
    ? { tone: "success", labelKey: "modelServices.status.inUse" }
    : { tone: "neutral", labelKey: "modelServices.status.draft" };
}

export function presentModelServiceOpen(closed: boolean): StatusTone {
  return closed
    ? { tone: "neutral", labelKey: "modelServices.status.closed" }
    : { tone: "success", labelKey: "modelServices.status.open" };
}

const INDEX_STATUS: Record<string, StatusTone> = {
  none: { tone: "neutral", labelKey: "modelServices.index.none" },
  indexing: { tone: "running", labelKey: "modelServices.index.indexing" },
  ready: { tone: "success", labelKey: "modelServices.index.ready" },
  failed: { tone: "danger", labelKey: "modelServices.index.failed" },
};

export function presentIndexStatus(status: string): StatusTone {
  return fromTable(INDEX_STATUS, status);
}

const TYPE_MAPPING_ORIGIN: Record<string, StatusTone> = {
  product: { tone: "neutral", labelKey: "typeMappings.origin.product" },
  job: { tone: "warning", labelKey: "typeMappings.origin.job" },
  user: { tone: "info", labelKey: "typeMappings.origin.user" },
};

export function presentTypeMappingOrigin(origin: string): StatusTone {
  return fromTable(TYPE_MAPPING_ORIGIN, origin);
}

export function presentProblemSeverity(
  severity: "error" | "warning" | undefined,
): Tone {
  return severity === "warning" ? "warning" : "danger";
}
