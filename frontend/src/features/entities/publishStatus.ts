import type { BusinessEntity, PublishStatus } from "@/features/entities/types";

export type EntityStatus = "not_serving" | "serving" | "deprecated";

export function entityStatus(entity: BusinessEntity): EntityStatus {
  if (entity.deprecated_at) {
    return "deprecated";
  }
  if (entity.ever_published) {
    return "serving";
  }
  return "not_serving";
}

export function entityStatusLabelKey(status: EntityStatus): string {
  if (status === "deprecated") {
    return "entities.status.deprecated";
  }
  if (status === "serving") {
    return "entities.status.serving";
  }
  return "entities.status.notServing";
}

export const ENTITY_STATUS_COLOR = {
  not_serving: "gray",
  serving: "green",
  deprecated: "red",
} as const;

export function publishStatusLabelKey(status: PublishStatus): string {
  if (status === "publishing") {
    return "entities.status.publishing";
  }
  if (status === "published") {
    return "entities.status.published";
  }
  return "entities.status.unpublished";
}

export const PUBLISH_STATUS_COLOR = {
  unpublished: "gray",
  publishing: "yellow",
  published: "green",
} as const;

export function canAuthor(entity: BusinessEntity): boolean {
  return (
    !entity.deprecated_at &&
    entity.current_version?.publish_status === "unpublished"
  );
}

export function isPublishing(entity: BusinessEntity): boolean {
  return entity.current_version?.publish_status === "publishing";
}
