import { describe, expect, it } from "vitest";

import {
  canAuthor,
  entityStatus,
  entityStatusLabelKey,
  isPublishing,
  publishStatusLabelKey,
} from "@/features/entities/publishStatus";
import type { BusinessEntity, PublishStatus } from "@/features/entities/types";

function entity(
  overrides: Partial<BusinessEntity> & {
    publish_status?: PublishStatus | null;
  } = {},
): BusinessEntity {
  const { publish_status = "unpublished", ...rest } = overrides;
  return {
    id: "ent_1",
    table_name: "material",
    name: "Material",
    description: "x",
    deprecated_at: null,
    ever_published: false,
    current_version: publish_status
      ? {
          id: "encv_1",
          version: 1,
          superseded: false,
          publish_status,
          table_name: null,
          alignment: {
            table_present: false,
            definition_ahead: true,
            latest_job_id: null,
            latest_job_status: null,
          },
        }
      : null,
    created_at: "2026-09-10T04:00:00Z",
    updated_at: "2026-09-10T04:00:00Z",
    ...rest,
  };
}

describe("entityStatus", () => {
  it("is not in service until a publish has succeeded", () => {
    expect(entityStatus(entity({ publish_status: "unpublished" }))).toBe(
      "not_serving",
    );
    expect(entityStatus(entity({ publish_status: "publishing" }))).toBe(
      "not_serving",
    );
  });

  it("stays in service when the current version is unpublished after a publish", () => {
    expect(
      entityStatus(
        entity({
          ever_published: true,
          publish_status: "unpublished",
        }),
      ),
    ).toBe("serving");
  });

  it("is in service while the current version is published", () => {
    expect(
      entityStatus(
        entity({
          ever_published: true,
          publish_status: "published",
        }),
      ),
    ).toBe("serving");
  });

  it("prefers deprecated and does not also report service", () => {
    expect(
      entityStatus(
        entity({
          deprecated_at: "2026-09-10T04:00:00Z",
          ever_published: true,
          publish_status: "published",
        }),
      ),
    ).toBe("deprecated");
  });
});

describe("entityStatusLabelKey", () => {
  it("maps each entity status to its own key", () => {
    expect(entityStatusLabelKey("not_serving")).toBe(
      "entities.status.notServing",
    );
    expect(entityStatusLabelKey("serving")).toBe("entities.status.serving");
    expect(entityStatusLabelKey("deprecated")).toBe(
      "entities.status.deprecated",
    );
  });
});

describe("publishStatusLabelKey", () => {
  it("maps each publish status without a deprecated tone", () => {
    expect(publishStatusLabelKey("unpublished")).toBe(
      "entities.status.unpublished",
    );
    expect(publishStatusLabelKey("publishing")).toBe(
      "entities.status.publishing",
    );
    expect(publishStatusLabelKey("published")).toBe(
      "entities.status.published",
    );
  });
});

describe("canAuthor", () => {
  it("is true only while the current version is unpublished and the entity is not deprecated", () => {
    expect(canAuthor(entity({ publish_status: "unpublished" }))).toBe(true);
    expect(canAuthor(entity({ publish_status: "publishing" }))).toBe(false);
    expect(canAuthor(entity({ publish_status: "published" }))).toBe(false);
    expect(
      canAuthor(
        entity({
          deprecated_at: "2026-09-10T04:00:00Z",
          publish_status: "unpublished",
        }),
      ),
    ).toBe(false);
  });
});

describe("isPublishing", () => {
  it("follows the current version only", () => {
    expect(isPublishing(entity({ publish_status: "publishing" }))).toBe(true);
    expect(isPublishing(entity({ publish_status: "unpublished" }))).toBe(false);
  });
});
