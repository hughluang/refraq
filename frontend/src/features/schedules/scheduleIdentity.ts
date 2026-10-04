import type { ScheduleTarget } from "@/features/schedules/types";

/** Site schedule default stored by the Metadata facade. Not the list primary. */
const CATALOG_EMBED_DEFAULT_NAME = "catalog embed";

export type ScheduleIdentityScope = "platform" | "source";

export type ScheduleIdentityInput = {
  name: string;
  work_kind: string | null;
  target: ScheduleTarget | null;
};

export type ScheduleIdentity = {
  primary: string;
  customName: string | null;
};

function targetToken(target: ScheduleTarget | null): string | null {
  const key = target?.source_key?.trim();
  if (key) return key;
  const id = target?.source_id?.trim();
  return id || null;
}

function defaultName(task: ScheduleIdentityInput): string | null {
  if (task.work_kind === "catalog_embed") return CATALOG_EMBED_DEFAULT_NAME;
  const key = task.target?.source_key?.trim();
  if (!key) return null;
  return `${task.work_kind} · ${key}`;
}

function primaryLine(
  task: ScheduleIdentityInput,
  scope: ScheduleIdentityScope,
): string {
  if (task.work_kind === "catalog_embed" || scope === "source") {
    return task.work_kind!;
  }
  return `${task.work_kind} · ${targetToken(task.target)}`;
}

export function scheduleIdentity(
  task: ScheduleIdentityInput,
  scope: ScheduleIdentityScope,
): ScheduleIdentity {
  const primary = primaryLine(task, scope);
  const name = task.name.trim();
  const baseline = defaultName(task) ?? primary;
  return { primary, customName: name === baseline ? null : name };
}

/** Modal title fragment: primary, with a custom name appended when present. */
export function scheduleIdentityLabel(
  task: ScheduleIdentityInput,
  scope: ScheduleIdentityScope,
): string {
  const { primary, customName } = scheduleIdentity(task, scope);
  return customName ? `${primary} · ${customName}` : primary;
}
