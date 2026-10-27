import type { BusinessEntity } from "@/features/entities/types";

export type EntityStatus = "not_serving" | "serving" | "deprecated";

export function entityStatus(entity: {
  deprecated_at: string | null;
  ever_published: boolean;
}): EntityStatus {
  if (entity.deprecated_at) {
    return "deprecated";
  }
  if (entity.ever_published) {
    return "serving";
  }
  return "not_serving";
}

export function canAuthor(entity: BusinessEntity): boolean {
  return (
    !entity.deprecated_at &&
    entity.current_version?.publish_status === "unpublished"
  );
}

export function isPublishing(entity: BusinessEntity): boolean {
  return entity.current_version?.publish_status === "publishing";
}
