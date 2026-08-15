import type { Job } from "@/features/jobs/types";

const KNOWN_TRIGGER_KINDS = new Set(["user", "schedule", "mcp", "system"]);

/** Truncate ``user_<suffix>`` refs for compact operator display. */
export function shortTriggerRef(ref: string): string {
  const match = /^user_(.+)$/.exec(ref);
  if (!match) return ref;
  const rest = match[1];
  if (rest.length <= 8) return ref;
  return `user_${rest.slice(0, 8)}`;
}

type TriggerFields = Pick<
  Job,
  "trigger_kind" | "trigger_ref" | "trigger_actor_name" | "trigger_schedule_name"
>;

/** Format Job trigger for operator-facing tables and detail. */
export function formatJobTrigger(
  job: TriggerFields,
  t: (key: string) => string,
): string {
  if (!job.trigger_kind) return "—";

  const kindLabel = KNOWN_TRIGGER_KINDS.has(job.trigger_kind)
    ? t(`jobs.trigger.${job.trigger_kind}`)
    : job.trigger_kind;

  if (job.trigger_kind === "user") {
    const who =
      job.trigger_actor_name ??
      (job.trigger_ref ? shortTriggerRef(job.trigger_ref) : null);
    return who ? `${kindLabel} · ${who}` : kindLabel;
  }

  if (job.trigger_kind === "schedule") {
    const label = job.trigger_schedule_name ?? job.trigger_ref;
    return label ? `${kindLabel} · ${label}` : kindLabel;
  }

  if (job.trigger_ref) {
    return `${kindLabel} · ${job.trigger_ref}`;
  }
  return kindLabel;
}
