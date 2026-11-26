import {
  copyProfile,
  createGrant,
  createProfile,
  createRestriction,
  deleteGrant,
  deleteProfile,
  deleteRestriction,
  getAccessSummary,
  patchGrant,
  patchProfile,
  patchRestriction,
  previewAccess,
  putLadder,
} from "@/features/entities/accessApi";
import {
  levelModeKind,
  literalOperand,
  operandText,
  validateLadder,
  type LadderLevel,
  type MaskMode,
  type RuleOp,
  type RuleOperand,
  type RuleOperandKind,
} from "@/features/entities/accessLogic";
import type {
  AccessGrant,
  AccessLadder,
  AccessProfile,
  AccessRestriction,
  AccessSubject,
  AccessSummary,
  PreviewAccessResponse,
  PreviewIdentity,
} from "@/features/entities/accessTypes";
import { ApiError } from "@/lib/api";

export const RULE_LEAF_MAX = 20;
export const RULE_DEPTH_MAX = 8;

export type RuleTreeNode =
  | { id: string; kind: "group"; op: "and" | "or"; children: RuleTreeNode[] }
  | { id: string; kind: "not"; child: RuleTreeNode }
  | { id: string; kind: "leaf"; op: RuleOp; attributeId: string; operand: RuleOperand };

export type NarrowSelection =
  | { kind: "none" }
  | { kind: "user" }
  | { kind: "role"; id: string }
  | { kind: "group"; id: string };

export type WorkbenchSelection =
  | null
  | { kind: "grant"; id: string }
  | { kind: "grant_new"; profileId?: string }
  | { kind: "profile"; id: string }
  | { kind: "profile_new" }
  | { kind: "profile_copy" }
  | { kind: "ladder"; attributeId: string }
  | { kind: "restriction"; id: string }
  | { kind: "restriction_new" };

export type SpecimenPin =
  | { kind: "profiles" }
  | {
      kind: "user";
      userId: string;
      displayName: string;
      narrow: NarrowSelection;
      includeRows: boolean;
    };

export type HoverTarget =
  | null
  | { kind: "grant"; id: string }
  | { kind: "profile"; id: string }
  | { kind: "restriction"; id: string }
  | { kind: "cell"; rowIndex: number; attributeName: string; sources: string[]; withheld: boolean };

export type WorkbenchProblem = {
  id: number;
  channel: "notification" | "field";
  error: unknown;
  retryable: boolean;
  savedKey?: string;
};

export type AccessPort = {
  loadSummary(entityId: string): Promise<AccessSummary>;
  putLadder(
    entityId: string,
    attributeId: string,
    levels: AccessLadder["levels"],
  ): Promise<{ policy_revision: number }>;
  createProfile(
    entityId: string,
    body: { key: string; name: string; description?: string | null; columns: { attribute_id: string; level: string }[] },
  ): Promise<{ profile: AccessProfile; policy_revision: number }>;
  patchProfile(
    entityId: string,
    profileId: string,
    body: { name?: string; description?: string | null; columns?: { attribute_id: string; level: string }[] },
  ): Promise<{ profile: AccessProfile; policy_revision: number }>;
  copyProfile(
    entityId: string,
    body: { source_entity_id: string; source_profile_id: string; key: string; name: string },
  ): Promise<{ profile: AccessProfile; dropped_columns: { attribute_name: string; reason: string }[]; policy_revision: number }>;
  deleteProfile(entityId: string, profileId: string): Promise<void>;
  createGrant(
    entityId: string,
    body: {
      subject: { type: string; id: string };
      profile_id: string;
      row_rule: Record<string, unknown> | null;
      actions: string[];
      status?: "active" | "disabled";
      valid_until?: string | null;
    },
  ): Promise<{ grant: AccessGrant; policy_revision: number }>;
  patchGrant(
    entityId: string,
    grantId: string,
    body: {
      profile_id?: string;
      row_rule?: Record<string, unknown> | null;
      actions?: string[];
      status?: "active" | "disabled";
      valid_until?: string | null;
    },
  ): Promise<{ grant: AccessGrant; policy_revision: number }>;
  deleteGrant(entityId: string, grantId: string): Promise<void>;
  createRestriction(
    entityId: string,
    body: {
      applies_to: { mode: string; subjects?: { type: string; id: string }[] };
      row_rule: Record<string, unknown> | null;
      deny_columns: string[];
      ceilings: { attribute_id: string; level: string }[];
      actions: string[];
    },
  ): Promise<{ restriction: AccessRestriction; policy_revision: number }>;
  patchRestriction(
    entityId: string,
    restrictionId: string,
    body: {
      applies_to?: { mode: string; subjects?: { type: string; id: string }[] };
      row_rule?: Record<string, unknown> | null;
      deny_columns?: string[];
      ceilings?: { attribute_id: string; level: string }[];
      actions?: string[];
    },
  ): Promise<{ restriction: AccessRestriction; policy_revision: number }>;
  deleteRestriction(entityId: string, restrictionId: string): Promise<void>;
  preview(
    entityId: string,
    body: {
      subject: { type: "user"; id: string };
      narrow?: { type: "user" | "role" | "group"; id?: string } | null;
      include_rows: boolean;
      limit?: number;
      offset?: number;
    },
  ): Promise<PreviewAccessResponse>;
};

export type LiveSchedulePort = {
  intervalMs: number;
  hidden(): boolean;
  subscribeVisibility(onVisible: () => void): () => void;
  setTimeout(cb: () => void, ms: number): ReturnType<typeof setTimeout>;
  clearTimeout(id: ReturnType<typeof setTimeout>): void;
};

export type WorkbenchNotification = {
  id: number;
  type: "success" | "error";
  savedKey?: string;
  error?: unknown;
  retry?: "load" | "preview";
};

export type AccessWorkbenchSnapshot = {
  entityId: string;
  canPreviewRows: boolean;
  phase: "loading" | "ready" | "unloaded";
  summary: AccessSummary | null;
  freshness: "current" | "stale";
  busyId: string | null;
  selection: WorkbenchSelection;
  pin: SpecimenPin;
  hover: HoverTarget;
  preview: PreviewAccessResponse | null;
  previewBusy: boolean;
  lastCopyDropped: { attribute_name: string; reason: string }[];
  lastNotification: WorkbenchNotification | null;
};

export type WorkbenchIntent =
  | { kind: "reload" }
  | { kind: "select"; selection: WorkbenchSelection }
  | { kind: "hover"; hover: HoverTarget }
  | { kind: "pin_profiles" }
  | { kind: "pin_user"; userId: string; displayName: string; narrow?: NarrowSelection; includeRows?: boolean }
  | { kind: "set_narrow"; narrow: NarrowSelection }
  | { kind: "set_include_rows"; includeRows: boolean }
  | { kind: "refresh_preview" }
  | { kind: "mutate"; busyId: string; savedKey: string; work: (port: AccessPort) => Promise<void> }
  | { kind: "set_profile_cell"; profileId: string; attributeId: string; level: string }
  | { kind: "toggle_grant_status"; grant: AccessGrant }
  | { kind: "copy_profile"; sourceEntityId: string; sourceProfileId: string; key: string; name: string };

export const httpAccessPort: AccessPort = {
  loadSummary: getAccessSummary,
  putLadder,
  createProfile,
  patchProfile,
  copyProfile,
  deleteProfile,
  createGrant,
  patchGrant,
  deleteGrant,
  createRestriction,
  patchRestriction,
  deleteRestriction,
  preview: previewAccess,
};

export function domLiveSchedule(intervalMs = 2000): LiveSchedulePort {
  return {
    intervalMs,
    hidden: () => typeof document !== "undefined" && document.visibilityState === "hidden",
    subscribeVisibility: (onVisible) => {
      if (typeof document === "undefined") return () => {};
      const handler = () => {
        if (document.visibilityState === "visible") onVisible();
      };
      document.addEventListener("visibilitychange", handler);
      return () => document.removeEventListener("visibilitychange", handler);
    },
    setTimeout: (cb, ms) => globalThis.setTimeout(cb, ms),
    clearTimeout: (id) => globalThis.clearTimeout(id),
  };
}

export type AccessWorkbenchSession = {
  snapshot(): AccessWorkbenchSnapshot;
  subscribe(listener: () => void): () => void;
  dispatch(intent: WorkbenchIntent): Promise<boolean>;
  dispose(): void;
};

export function openAccessWorkbench(deps: {
  entityId: string;
  canPreviewRows: boolean;
  port?: AccessPort;
  schedule?: LiveSchedulePort;
}): AccessWorkbenchSession {
  const port = deps.port ?? httpAccessPort;
  const schedule = deps.schedule ?? domLiveSchedule();
  const listeners = new Set<() => void>();
  let disposed = false;
  let generation = 0;
  let notifySeq = 0;
  let pollTimer: ReturnType<typeof setTimeout> | null = null;
  let unsubVisibility: (() => void) | null = null;

  let state: AccessWorkbenchSnapshot = {
    entityId: deps.entityId,
    canPreviewRows: deps.canPreviewRows,
    phase: "loading",
    summary: null,
    freshness: "current",
    busyId: null,
    selection: null,
    pin: { kind: "profiles" },
    hover: null,
    preview: null,
    previewBusy: false,
    lastCopyDropped: [],
    lastNotification: null,
  };

  function emit() {
    if (disposed) return;
    for (const listener of listeners) listener();
  }

  function clearPoll() {
    if (pollTimer !== null) {
      schedule.clearTimeout(pollTimer);
      pollTimer = null;
    }
    if (unsubVisibility) {
      unsubVisibility();
      unsubVisibility = null;
    }
  }

  function schedulePoll(summary: AccessSummary | null) {
    clearPoll();
    if (disposed || !summary || summary.head_version_id == null || summary.views.state !== "pending") {
      return;
    }
    if (schedule.hidden()) {
      unsubVisibility = schedule.subscribeVisibility(() => {
        unsubVisibility?.();
        unsubVisibility = null;
        void pollOnce();
      });
      return;
    }
    pollTimer = schedule.setTimeout(() => {
      pollTimer = null;
      void pollOnce();
    }, schedule.intervalMs);
  }

  async function pollOnce() {
    if (disposed) return;
    const gen = generation;
    try {
      const next = await port.loadSummary(deps.entityId);
      if (disposed || gen !== generation) return;
      state = {
        ...state,
        phase: "ready",
        summary: next,
        freshness: "current",
      };
      emit();
      schedulePoll(next);
    } catch {
      if (disposed || gen !== generation) return;
      state = { ...state, freshness: "stale" };
      emit();
      schedulePoll(state.summary);
    }
  }

  async function loadSummaryNow(): Promise<boolean> {
    const gen = ++generation;
    clearPoll();
    if (state.summary == null) {
      state = { ...state, phase: "loading" };
      emit();
    }
    try {
      const next = await port.loadSummary(deps.entityId);
      if (disposed || gen !== generation) return false;
      state = {
        ...state,
        phase: "ready",
        summary: next,
        freshness: "current",
      };
      emit();
      schedulePoll(next);
      return true;
    } catch (err) {
      if (disposed || gen !== generation) return false;
      state = {
        ...state,
        phase: state.summary == null ? "unloaded" : "ready",
        lastNotification: {
          id: ++notifySeq,
          type: "error",
          error: err,
          retry: "load",
        },
      };
      emit();
      return false;
    }
  }

  async function runPreview(pin: Extract<SpecimenPin, { kind: "user" }>): Promise<boolean> {
    const gen = generation;
    state = { ...state, previewBusy: true };
    emit();
    try {
      const narrow =
        pin.narrow.kind === "none"
          ? null
          : pin.narrow.kind === "user"
            ? { type: "user" as const }
            : { type: pin.narrow.kind, id: pin.narrow.id };
      const res = await port.preview(deps.entityId, {
        subject: { type: "user", id: pin.userId },
        narrow,
        include_rows: pin.includeRows && deps.canPreviewRows,
      });
      if (disposed || gen !== generation) return false;
      state = { ...state, preview: res, previewBusy: false };
      emit();
      return true;
    } catch (err) {
      if (disposed || gen !== generation) return false;
      state = {
        ...state,
        preview: null,
        previewBusy: false,
        lastNotification: {
          id: ++notifySeq,
          type: "error",
          error: err,
          retry: "preview",
        },
      };
      emit();
      return false;
    }
  }

  async function runMutation(
    busyId: string,
    savedKey: string,
    work: () => Promise<void>,
  ): Promise<boolean> {
    if (state.busyId !== null) return false;
    state = { ...state, busyId };
    emit();
    try {
      await work();
      if (disposed) return false;
      const loaded = await loadSummaryNow();
      if (disposed) return false;
      if (loaded && state.pin.kind === "user") {
        void runPreview(state.pin);
      }
      state = {
        ...state,
        busyId: null,
        lastNotification: {
          id: ++notifySeq,
          type: "success",
          savedKey,
        },
      };
      emit();
      return true;
    } catch (err) {
      if (disposed) return false;
      state = {
        ...state,
        busyId: null,
        lastNotification: {
          id: ++notifySeq,
          type: "error",
          error: err,
        },
      };
      emit();
      return false;
    }
  }

  void loadSummaryNow();

  return {
    snapshot: () => state,
    subscribe: (listener) => {
      listeners.add(listener);
      return () => {
        listeners.delete(listener);
      };
    },
    dispose: () => {
      disposed = true;
      clearPoll();
      listeners.clear();
    },
    dispatch: async (intent) => {
      if (disposed) return false;
      switch (intent.kind) {
        case "reload":
          return loadSummaryNow();
        case "select":
          state = { ...state, selection: intent.selection, lastCopyDropped: [] };
          emit();
          return true;
        case "hover":
          state = { ...state, hover: intent.hover };
          emit();
          return true;
        case "pin_profiles":
          state = { ...state, pin: { kind: "profiles" }, preview: null, hover: null };
          emit();
          return true;
        case "pin_user": {
          const pin: Extract<SpecimenPin, { kind: "user" }> = {
            kind: "user",
            userId: intent.userId,
            displayName: intent.displayName,
            narrow: intent.narrow ?? { kind: "none" },
            includeRows: Boolean(intent.includeRows && deps.canPreviewRows),
          };
          state = { ...state, pin, hover: null };
          emit();
          return runPreview(pin);
        }
        case "set_narrow": {
          if (state.pin.kind !== "user") return false;
          const pin = { ...state.pin, narrow: intent.narrow };
          state = { ...state, pin };
          emit();
          return runPreview(pin);
        }
        case "set_include_rows": {
          if (state.pin.kind !== "user") return false;
          const pin = { ...state.pin, includeRows: intent.includeRows && deps.canPreviewRows };
          state = { ...state, pin };
          emit();
          return runPreview(pin);
        }
        case "refresh_preview":
          if (state.pin.kind !== "user") return false;
          return runPreview(state.pin);
        case "mutate":
          return runMutation(intent.busyId, intent.savedKey, () => intent.work(port));
        case "set_profile_cell": {
          const profile = state.summary?.profiles.find((p) => p.id === intent.profileId);
          if (!profile) return false;
          const nextCols = profile.columns
            .filter((c) => c.attribute_id !== intent.attributeId)
            .map((c) => ({ attribute_id: c.attribute_id, level: c.level }));
          if (intent.level) {
            nextCols.push({ attribute_id: intent.attributeId, level: intent.level });
          }
          return runMutation(`profile-cell:${intent.profileId}`, "entities.access.saved.profiles", async () => {
            await port.patchProfile(deps.entityId, intent.profileId, { columns: nextCols });
          });
        }
        case "toggle_grant_status": {
          if (intent.grant.locked) return false;
          const nextStatus = intent.grant.status === "active" ? "disabled" : "active";
          return runMutation(`grant-status:${intent.grant.id}`, "entities.access.saved.grants", async () => {
            await port.patchGrant(deps.entityId, intent.grant.id, { status: nextStatus });
          });
        }
        case "copy_profile":
          return runMutation("profile-copy", "entities.access.saved.copied", async () => {
            const res = await port.copyProfile(deps.entityId, {
              source_entity_id: intent.sourceEntityId,
              source_profile_id: intent.sourceProfileId,
              key: intent.key,
              name: intent.name,
            });
            state = { ...state, lastCopyDropped: res.dropped_columns ?? [] };
          });
      }
    },
  };
}

let ruleSeq = 0;
function nextRuleId(): string {
  ruleSeq += 1;
  return `r_${ruleSeq}`;
}

export function parseRuleTree(raw: Record<string, unknown> | null): RuleTreeNode | null {
  if (raw == null) return null;
  const entries = Object.entries(raw);
  if (entries.length !== 1) return null;
  const [key, body] = entries[0] ?? [];
  if (key === "and" || key === "or") {
    if (!Array.isArray(body) || body.length === 0) return null;
    const children = body
      .map((item) =>
        typeof item === "object" && item !== null && !Array.isArray(item)
          ? parseRuleTree(item as Record<string, unknown>)
          : null,
      )
      .filter((item): item is RuleTreeNode => item !== null);
    if (children.length === 0) return null;
    return { id: nextRuleId(), kind: "group", op: key, children };
  }
  if (key === "not") {
    if (typeof body !== "object" || body === null || Array.isArray(body)) return null;
    const child = parseRuleTree(body as Record<string, unknown>);
    if (!child) return null;
    return { id: nextRuleId(), kind: "not", child };
  }
  if (typeof body !== "object" || body === null || Array.isArray(body)) return null;
  const record = body as Record<string, unknown>;
  if (typeof record.attr !== "string") return null;
  const operand = parseRuleOperand(record);
  if (!operand) return null;
  return {
    id: nextRuleId(),
    kind: "leaf",
    op: key as RuleOp,
    attributeId: record.attr,
    operand,
  };
}

function parseRuleOperand(record: Record<string, unknown>): RuleOperand | null {
  if ("value" in record) return { kind: "value", value: record.value };
  if (typeof record.subject_attr === "string") {
    return { kind: "subject_attr", key: record.subject_attr };
  }
  if (record.subject_id === true) return { kind: "subject_id" };
  if (typeof record.rel_time === "string") {
    return { kind: "rel_time", duration: record.rel_time };
  }
  return null;
}

export function serializeRuleTree(node: RuleTreeNode | null): Record<string, unknown> | null {
  if (!node) return null;
  if (node.kind === "group") {
    const items = node.children
      .map((child) => serializeRuleTree(child))
      .filter((item): item is Record<string, unknown> => item !== null);
    if (items.length === 0) return null;
    return { [node.op]: items };
  }
  if (node.kind === "not") {
    const inner = serializeRuleTree(node.child);
    if (!inner) return null;
    return { not: inner };
  }
  const body: Record<string, unknown> = { attr: node.attributeId };
  const op = node.operand;
  if (op.kind === "value") body.value = op.value;
  if (op.kind === "subject_attr") body.subject_attr = op.key;
  if (op.kind === "subject_id") body.subject_id = true;
  if (op.kind === "rel_time") body.rel_time = op.duration;
  return { [node.op]: body };
}

export function ruleTreeMetrics(node: RuleTreeNode | null): {
  leaves: number;
  depth: number;
  overCap: boolean;
} {
  if (!node) return { leaves: 0, depth: 0, overCap: false };
  const walk = (item: RuleTreeNode, depth: number): { leaves: number; maxDepth: number } => {
    if (item.kind === "leaf") return { leaves: 1, maxDepth: depth };
    if (item.kind === "not") return walk(item.child, depth + 1);
    let leaves = 0;
    let maxDepth = depth;
    for (const child of item.children) {
      const sub = walk(child, depth + 1);
      leaves += sub.leaves;
      if (sub.maxDepth > maxDepth) maxDepth = sub.maxDepth;
    }
    return { leaves, maxDepth };
  };
  const { leaves, maxDepth } = walk(node, 1);
  return {
    leaves,
    depth: maxDepth,
    overCap: leaves > RULE_LEAF_MAX || maxDepth > RULE_DEPTH_MAX,
  };
}

export function makeDefaultLeaf(ladder: AccessLadder): Extract<RuleTreeNode, { kind: "leaf" }> {
  const ops = ladder.operators?.length ? (ladder.operators as RuleOp[]) : (["eq"] as RuleOp[]);
  const op = ops[0] ?? "eq";
  return {
    id: nextRuleId(),
    kind: "leaf",
    op,
    attributeId: ladder.attribute_id,
    operand: { kind: "value", value: op === "is_null" ? true : "" },
  };
}

export function availableOperandKinds(
  ladder: AccessLadder | undefined,
  op: RuleOp,
): RuleOperandKind[] {
  const kinds: RuleOperandKind[] = ["value"];
  if (!ladder) return kinds;
  const valueType = ladder.value_type ?? ladder.type;
  if (op === "in" && (ladder.compatible_subject_attributes?.length ?? 0) > 0) {
    kinds.push("subject_attr");
  }
  if ((op === "eq" || op === "ne") && valueType === "user") {
    kinds.push("subject_id");
  }
  if (
    ["lt", "lte", "gt", "gte"].includes(op) &&
    (valueType === "date" || valueType === "timestamp")
  ) {
    kinds.push("rel_time");
  }
  return kinds;
}

export function formatRelTimeDuration(
  direction: "past" | "future",
  amount: number,
  unit: "Y" | "M" | "D" | "H" | "MI" | "S",
): string {
  const safe = Math.max(1, Math.floor(amount || 1));
  const prefix = direction === "past" ? "-P" : "P";
  if (unit === "H" || unit === "MI" || unit === "S") {
    const code = unit === "MI" ? "M" : unit;
    return `${prefix}T${safe}${code}`;
  }
  return `${prefix}${safe}${unit}`;
}

export function parseRelTimeDuration(raw: string): {
  direction: "past" | "future";
  amount: number;
  unit: "Y" | "M" | "D" | "H" | "MI" | "S";
} {
  const match = /^(-)?P(?:(\d+)Y)?(?:(\d+)M)?(?:(\d+)D)?(?:T(?:(\d+)H)?(?:(\d+)M)?(?:(\d+)S)?)?$/.exec(
    raw.trim(),
  );
  if (!match) return { direction: "past", amount: 30, unit: "D" };
  const direction = match[1] ? "past" : "future";
  if (match[2]) return { direction, amount: Number(match[2]), unit: "Y" };
  if (match[3]) return { direction, amount: Number(match[3]), unit: "M" };
  if (match[4]) return { direction, amount: Number(match[4]), unit: "D" };
  if (match[5]) return { direction, amount: Number(match[5]), unit: "H" };
  if (match[6]) return { direction, amount: Number(match[6]), unit: "MI" };
  if (match[7]) return { direction, amount: Number(match[7]), unit: "S" };
  return { direction, amount: 30, unit: "D" };
}

export function sampleRawValue(ladder: AccessLadder): string {
  const name = ladder.attribute_name.toLowerCase();
  const valueType = ladder.value_type ?? ladder.type;
  if (valueType === "date") return "2026-11-26";
  if (valueType === "timestamp") return "2026-11-26T14:30:00Z";
  if (valueType === "integer") return "128450";
  if (valueType === "decimal" || valueType === "number") return "12845.75";
  if (valueType === "boolean") return "true";
  if (valueType === "dictionary") return ladder.codes?.[0] ?? "active";
  if (valueType === "user") return "usr_ada_01";
  if (name.includes("mail")) return "ada@refraq.io";
  if (name.includes("phone") || name.includes("mobile") || name.includes("tel")) return "13800138000";
  if (name.includes("id_card") || name.includes("ssn") || name.includes("card")) return "310101199001011234";
  return "SampleValue";
}

/** Deterministic in-process specimen sample formatter for live mask tuning. */
export function formatMaskSample(
  ladder: AccessLadder,
  mode: MaskMode | "clear" | { type: string; [key: string]: unknown },
  rawOverride?: string,
): string {
  const raw = rawOverride ?? sampleRawValue(ladder);
  if (mode === "clear") return raw;
  switch (mode.type) {
    case "null":
      return "NULL";
    case "redact":
      return "[redacted]";
    case "hash": {
      let acc = 2166136261;
      for (let i = 0; i < raw.length; i += 1) {
        acc ^= raw.charCodeAt(i);
        acc = Math.imul(acc, 16777619);
      }
      const hex = (acc >>> 0).toString(16).padStart(8, "0");
      return `h_${hex}…`;
    }
    case "email": {
      const at = raw.indexOf("@");
      if (at <= 0) return `${raw.slice(0, 1)}***`;
      return `${raw.slice(0, 1)}***@${raw.slice(at + 1)}`;
    }
    case "partial": {
      const kfRaw = typeof mode.keep_first === "number" ? mode.keep_first : 0;
      const klRaw = typeof mode.keep_last === "number" ? mode.keep_last : 0;
      const kf = Math.max(0, Math.min(64, Math.floor(kfRaw)));
      const kl = Math.max(0, Math.min(64, Math.floor(klRaw)));
      if (raw.length <= kf + kl) return "*".repeat(raw.length);
      const mid = Math.max(2, raw.length - kf - kl);
      return `${raw.slice(0, kf)}${"*".repeat(mid)}${kl > 0 ? raw.slice(-kl) : ""}`;
    }
    case "truncate_date": {
      const day = raw.slice(0, 10);
      if (mode.unit === "year") return `${day.slice(0, 4)}-01-01`;
      if (mode.unit === "month") return `${day.slice(0, 7)}-01`;
      return day;
    }
    case "bucket": {
      const num = Number(raw);
      const widthRaw = typeof mode.width === "number" ? mode.width : 10;
      const w = widthRaw > 0 ? widthRaw : 10;
      if (!Number.isFinite(num)) return raw;
      return String(Math.floor(num / w) * w);
    }
    default:
      return raw;
  }
}

export function levelRevealRank(ladder: AccessLadder, levelKey: string): number {
  const idx = ladder.levels.findIndex((item) => item.key === levelKey);
  return idx === -1 ? Number.POSITIVE_INFINITY : idx;
}

export function effectiveCeilingForColumn(
  restrictions: AccessRestriction[],
  attributeId: string,
): { denied: boolean; ceilingLevel: string | null } {
  const denied = restrictions.some((r) => r.deny_columns.includes(attributeId));
  const ceiling = restrictions.find((r) => r.ceilings.some((c) => c.attribute_id === attributeId))
    ?.ceilings.find((c) => c.attribute_id === attributeId)?.level ?? null;
  return { denied, ceilingLevel: ceiling };
}

export function summarizeRuleCompact(
  node: RuleTreeNode | null,
  t: (key: string, options?: Record<string, unknown>) => string,
  attributeName: (id: string) => string,
  attributeType: (id: string) => string | null,
): string {
  if (!node) return t("entities.access.grants.allRows");
  if (node.kind === "leaf") {
    const opKey =
      attributeType(node.attributeId) &&
      ["date", "timestamp"].includes(attributeType(node.attributeId) ?? "") &&
      ["lt", "lte", "gt", "gte"].includes(node.op)
        ? `entities.access.rule.op.${node.op}.time`
        : `entities.access.rule.op.${node.op}`;
    const target =
      node.operand.kind === "subject_id"
        ? t("entities.access.rule.subjectId")
        : operandText(node.operand);
    return `${attributeName(node.attributeId)} ${t(opKey)} ${target}`.trim();
  }
  if (node.kind === "not") {
    return `NOT (${summarizeRuleCompact(node.child, t, attributeName, attributeType)})`;
  }
  const joiner = node.op === "and" ? ` ${t("entities.access.summary.and")} ` : ` ${t("entities.access.summary.or")} `;
  return node.children
    .map((child) => summarizeRuleCompact(child, t, attributeName, attributeType))
    .join(joiner);
}

/** In-memory AccessPort adapter for fast, deterministic tests without vi.mock. */
export type MemoryAccessPort = AccessPort & {
  commands: { op: string; payload: unknown }[];
  setSummary(next: AccessSummary): void;
  setPreview(next: PreviewAccessResponse): void;
  failNext(method: keyof AccessPort, error: unknown): void;
  completeViews(): void;
};

export function memoryAccessPort(
  initialSummary: AccessSummary,
  initialPreview?: PreviewAccessResponse,
): MemoryAccessPort {
  let currentSummary: AccessSummary = structuredClone(initialSummary);
  let currentPreview: PreviewAccessResponse = initialPreview ?? {
    policy_revision: initialSummary.policy_revision,
    identities: [{ type: "user", id: null, display_name: "User" }],
    effective_grants: [],
    schema: {
      entity: { table_name: "entity", writable: false, name: "Entity" },
      attributes: [],
      withheld_field: null,
      business_key: null,
    },
    rows: null,
  };
  const failures = new Map<keyof AccessPort, unknown>();
  const commands: { op: string; payload: unknown }[] = [];
  let seq = 0;

  function checkFail(method: keyof AccessPort) {
    if (failures.has(method)) {
      const err = failures.get(method);
      failures.delete(method);
      throw err;
    }
  }

  function bumpRevision() {
    currentSummary = {
      ...currentSummary,
      policy_revision: currentSummary.policy_revision + 1,
    };
  }

  return {
    commands,
    setSummary(next) {
      currentSummary = structuredClone(next);
    },
    setPreview(next) {
      currentPreview = structuredClone(next);
    },
    failNext(method, error) {
      failures.set(method, error);
    },
    completeViews() {
      currentSummary = {
        ...currentSummary,
        views: {
          ...currentSummary.views,
          state: "ready",
          revision: currentSummary.policy_revision,
        },
      };
    },
    async loadSummary() {
      checkFail("loadSummary");
      return structuredClone(currentSummary);
    },
    async putLadder(_entityId, attributeId, levels) {
      checkFail("putLadder");
      commands.push({ op: "putLadder", payload: { attributeId, levels } });
      currentSummary = {
        ...currentSummary,
        ladders: currentSummary.ladders.map((l) =>
          l.attribute_id === attributeId ? { ...l, levels: structuredClone(levels) } : l,
        ),
      };
      bumpRevision();
      return { policy_revision: currentSummary.policy_revision };
    },
    async createProfile(_entityId, body) {
      checkFail("createProfile");
      commands.push({ op: "createProfile", payload: body });
      const created: AccessProfile = {
        id: `eap_mem_${++seq}`,
        entity_id: currentSummary.entity_id,
        key: body.key,
        name: body.name,
        description: body.description ?? null,
        columns: body.columns.map((c) => ({ ...c })),
        broken: false,
        broken_reasons: [],
      };
      currentSummary = { ...currentSummary, profiles: [...currentSummary.profiles, created] };
      bumpRevision();
      return { profile: structuredClone(created), policy_revision: currentSummary.policy_revision };
    },
    async patchProfile(_entityId, profileId, body) {
      checkFail("patchProfile");
      commands.push({ op: "patchProfile", payload: { profileId, body } });
      let updated: AccessProfile | undefined;
      currentSummary = {
        ...currentSummary,
        profiles: currentSummary.profiles.map((p) => {
          if (p.id !== profileId) return p;
          updated = {
            ...p,
            name: body.name ?? p.name,
            description: body.description !== undefined ? body.description : p.description,
            columns: body.columns ? body.columns.map((c) => ({ ...c })) : p.columns,
          };
          return updated;
        }),
      };
      if (!updated) throw new ApiError(404, "ENTITY_ACCESS_PROFILE_NOT_FOUND", "missing");
      bumpRevision();
      return { profile: structuredClone(updated), policy_revision: currentSummary.policy_revision };
    },
    async copyProfile(_entityId, body) {
      checkFail("copyProfile");
      commands.push({ op: "copyProfile", payload: body });
      const created: AccessProfile = {
        id: `eap_mem_${++seq}`,
        entity_id: currentSummary.entity_id,
        key: body.key,
        name: body.name,
        description: null,
        columns: [],
        broken: false,
        broken_reasons: [],
      };
      currentSummary = { ...currentSummary, profiles: [...currentSummary.profiles, created] };
      bumpRevision();
      return {
        profile: structuredClone(created),
        dropped_columns: [],
        policy_revision: currentSummary.policy_revision,
      };
    },
    async deleteProfile(_entityId, profileId) {
      checkFail("deleteProfile");
      commands.push({ op: "deleteProfile", payload: { profileId } });
      currentSummary = {
        ...currentSummary,
        profiles: currentSummary.profiles.filter((p) => p.id !== profileId),
      };
      bumpRevision();
    },
    async createGrant(_entityId, body) {
      checkFail("createGrant");
      commands.push({ op: "createGrant", payload: body });
      const created: AccessGrant = {
        id: `eag_mem_${++seq}`,
        subject: {
          type: body.subject.type as AccessSubject["type"],
          id: body.subject.id,
          display_name: body.subject.id,
          missing: false,
        },
        profile_id: body.profile_id,
        row_rule: body.row_rule,
        actions: [...body.actions],
        status: body.status ?? "active",
        locked: false,
        valid_until: body.valid_until ?? null,
        broken: false,
      };
      currentSummary = { ...currentSummary, grants: [created, ...currentSummary.grants] };
      bumpRevision();
      return { grant: structuredClone(created), policy_revision: currentSummary.policy_revision };
    },
    async patchGrant(_entityId, grantId, body) {
      checkFail("patchGrant");
      commands.push({ op: "patchGrant", payload: { grantId, body } });
      let updated: AccessGrant | undefined;
      currentSummary = {
        ...currentSummary,
        grants: currentSummary.grants.map((g) => {
          if (g.id !== grantId) return g;
          updated = {
            ...g,
            profile_id: body.profile_id ?? g.profile_id,
            row_rule: body.row_rule !== undefined ? body.row_rule : g.row_rule,
            actions: body.actions ? [...body.actions] : g.actions,
            status: body.status ?? g.status,
            valid_until: body.valid_until !== undefined ? body.valid_until : g.valid_until,
          };
          return updated;
        }),
      };
      if (!updated) throw new ApiError(404, "ENTITY_ACCESS_GRANT_NOT_FOUND", "missing");
      bumpRevision();
      return { grant: structuredClone(updated), policy_revision: currentSummary.policy_revision };
    },
    async deleteGrant(_entityId, grantId) {
      checkFail("deleteGrant");
      commands.push({ op: "deleteGrant", payload: { grantId } });
      currentSummary = {
        ...currentSummary,
        grants: currentSummary.grants.filter((g) => g.id !== grantId),
      };
      bumpRevision();
    },
    async createRestriction(_entityId, body) {
      checkFail("createRestriction");
      commands.push({ op: "createRestriction", payload: body });
      const created: AccessRestriction = {
        id: `ear_mem_${++seq}`,
        applies_to: {
          mode: body.applies_to.mode,
          subjects: (body.applies_to.subjects ?? []).map((s) => ({
            type: s.type as AccessSubject["type"],
            id: s.id,
            display_name: s.id,
          })),
        },
        row_rule: body.row_rule,
        deny_columns: [...body.deny_columns],
        ceilings: body.ceilings.map((c) => ({ ...c })),
        actions: [...body.actions],
      };
      currentSummary = {
        ...currentSummary,
        restrictions: [created, ...currentSummary.restrictions],
      };
      bumpRevision();
      return { restriction: structuredClone(created), policy_revision: currentSummary.policy_revision };
    },
    async patchRestriction(_entityId, restrictionId, body) {
      checkFail("patchRestriction");
      commands.push({ op: "patchRestriction", payload: { restrictionId, body } });
      let updated: AccessRestriction | undefined;
      currentSummary = {
        ...currentSummary,
        restrictions: currentSummary.restrictions.map((r) => {
          if (r.id !== restrictionId) return r;
          updated = {
            ...r,
            applies_to: body.applies_to
              ? {
                  mode: body.applies_to.mode,
                  subjects: (body.applies_to.subjects ?? []).map((s) => ({
                    type: s.type as AccessSubject["type"],
                    id: s.id,
                    display_name: s.id,
                  })),
                }
              : r.applies_to,
            row_rule: body.row_rule !== undefined ? body.row_rule : r.row_rule,
            deny_columns: body.deny_columns ? [...body.deny_columns] : r.deny_columns,
            ceilings: body.ceilings ? body.ceilings.map((c) => ({ ...c })) : r.ceilings,
            actions: body.actions ? [...body.actions] : r.actions,
          };
          return updated;
        }),
      };
      if (!updated) throw new ApiError(404, "ENTITY_ACCESS_RESTRICTION_NOT_FOUND", "missing");
      bumpRevision();
      return { restriction: structuredClone(updated), policy_revision: currentSummary.policy_revision };
    },
    async deleteRestriction(_entityId, restrictionId) {
      checkFail("deleteRestriction");
      commands.push({ op: "deleteRestriction", payload: { restrictionId } });
      currentSummary = {
        ...currentSummary,
        restrictions: currentSummary.restrictions.filter((r) => r.id !== restrictionId),
      };
      bumpRevision();
    },
    async preview(_entityId, body) {
      checkFail("preview");
      commands.push({ op: "preview", payload: body });
      return structuredClone(currentPreview);
    },
  };
}

export type ManualLiveSchedule = LiveSchedulePort & {
  tick(): Promise<void>;
  setHidden(next: boolean): void;
  pendingCount(): number;
};

export function manualLiveSchedule(intervalMs = 2000): ManualLiveSchedule {
  let isHidden = false;
  let timerSeq = 0;
  const timers = new Map<number, () => void>();
  const visListeners = new Set<() => void>();

  return {
    intervalMs,
    hidden: () => isHidden,
    subscribeVisibility: (onVisible) => {
      visListeners.add(onVisible);
      return () => visListeners.delete(onVisible);
    },
    setTimeout: (cb) => {
      const id = ++timerSeq;
      timers.set(id, cb);
      return id as unknown as ReturnType<typeof setTimeout>;
    },
    clearTimeout: (id) => {
      timers.delete(id as unknown as number);
    },
    setHidden(next) {
      isHidden = next;
      if (!next) {
        for (const fn of [...visListeners]) fn();
      }
    },
    pendingCount: () => timers.size,
    async tick() {
      const batch = [...timers.entries()];
      timers.clear();
      for (const [, cb] of batch) {
        cb();
      }
      await Promise.resolve();
      await Promise.resolve();
    },
  };
}

export {
  levelModeKind,
  literalOperand,
  validateLadder,
  type LadderLevel,
  type MaskMode,
  type PreviewIdentity,
};
