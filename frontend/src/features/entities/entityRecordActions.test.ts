import { describe, expect, it } from "vitest";

import {
  entityRecordHeaderActions,
  type EntityRecordActionFlags,
} from "@/features/entities/entityRecordActions";

const unpublished: EntityRecordActionFlags = {
  mode: "show",
  canWrite: true,
  canAuthor: true,
  publishing: false,
  deprecated: false,
  published: false,
  everPublished: false,
  hasCurrentVersion: true,
};

describe("entityRecordHeaderActions", () => {
  it("create is only the standard cluster with cancel", () => {
    const actions = entityRecordHeaderActions({
      ...unpublished,
      mode: "create",
      canAuthor: false,
      hasCurrentVersion: false,
    });
    expect(actions.clusters).toEqual(["standard"]);
    expect(actions.navigation).toBe(false);
    expect(actions.lifecycle).toBe(false);
    expect(actions.cancel).toBe(true);
    expect(actions.publish).toBe(false);
    expect(actions.edit).toBe(false);
    expect(actions.deleteEntity).toBe(false);
    expect(actions.publishFilled).toBe(false);
  });

  it("show unpublished: nav, publish filled, edit and delete", () => {
    const actions = entityRecordHeaderActions(unpublished);
    expect(actions.clusters).toEqual([
      "navigation",
      "lifecycle",
      "standard",
    ]);
    expect(actions.publish).toBe(true);
    expect(actions.publishFilled).toBe(true);
    expect(actions.openVersion).toBe(false);
    expect(actions.deprecate).toBe(false);
    expect(actions.edit).toBe(true);
    expect(actions.deleteEntity).toBe(true);
    expect(actions.cancel).toBe(false);
  });

  it("edit unpublished: nav, publish light, delete and cancel", () => {
    const actions = entityRecordHeaderActions({
      ...unpublished,
      mode: "edit",
    });
    expect(actions.clusters).toEqual([
      "navigation",
      "lifecycle",
      "standard",
    ]);
    expect(actions.publish).toBe(true);
    expect(actions.publishFilled).toBe(false);
    expect(actions.edit).toBe(false);
    expect(actions.deleteEntity).toBe(true);
    expect(actions.cancel).toBe(true);
  });

  it("show published: open version and deprecate, no edit delete or cancel", () => {
    const actions = entityRecordHeaderActions({
      ...unpublished,
      canAuthor: false,
      published: true,
      everPublished: true,
    });
    expect(actions.clusters).toEqual(["navigation", "lifecycle"]);
    expect(actions.publish).toBe(false);
    expect(actions.openVersion).toBe(true);
    expect(actions.deprecate).toBe(true);
    expect(actions.edit).toBe(false);
    expect(actions.deleteEntity).toBe(false);
    expect(actions.cancel).toBe(false);
    expect(actions.standard).toBe(false);
  });

  it("publishing keeps navigation and drops write actions", () => {
    const actions = entityRecordHeaderActions({
      ...unpublished,
      canAuthor: false,
      publishing: true,
    });
    expect(actions.clusters).toEqual(["navigation"]);
    expect(actions.publish).toBe(false);
    expect(actions.openVersion).toBe(false);
    expect(actions.deprecate).toBe(false);
    expect(actions.edit).toBe(false);
    expect(actions.deleteEntity).toBe(false);
    expect(actions.cancel).toBe(false);
  });

  it("deprecated keeps navigation only", () => {
    const actions = entityRecordHeaderActions({
      ...unpublished,
      canAuthor: false,
      published: true,
      everPublished: true,
      deprecated: true,
    });
    expect(actions.clusters).toEqual(["navigation"]);
    expect(actions.deprecate).toBe(false);
    expect(actions.openVersion).toBe(false);
  });

  it("read-only show is navigation only", () => {
    const actions = entityRecordHeaderActions({
      ...unpublished,
      canWrite: false,
    });
    expect(actions.clusters).toEqual(["navigation"]);
    expect(actions.lifecycle).toBe(false);
    expect(actions.standard).toBe(false);
  });
});
