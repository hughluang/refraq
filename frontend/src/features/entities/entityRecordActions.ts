export const ENTITY_RECORD_FORM_ID = "entity-record-form";

export type EntityRecordMode = "create" | "show" | "edit";

export type EntityRecordActionCluster =
  | "navigation"
  | "lifecycle"
  | "standard";

export type EntityRecordActionFlags = {
  mode: EntityRecordMode;
  canWrite: boolean;
  canAuthor: boolean;
  publishing: boolean;
  deprecated: boolean;
  published: boolean;
  everPublished: boolean;
  hasCurrentVersion: boolean;
};

export type EntityRecordHeaderActions = {
  navigation: boolean;
  publish: boolean;
  openVersion: boolean;
  deprecate: boolean;
  edit: boolean;
  deleteEntity: boolean;
  cancel: boolean;
  lifecycle: boolean;
  standard: boolean;
  publishFilled: boolean;
  clusters: EntityRecordActionCluster[];
};

export function entityRecordHeaderActions(
  flags: EntityRecordActionFlags,
): EntityRecordHeaderActions {
  const create = flags.mode === "create";
  const show = flags.mode === "show";
  const edit = flags.mode === "edit";

  const navigation = !create;
  const publish =
    !create && flags.canWrite && flags.canAuthor && flags.hasCurrentVersion;
  const openVersion =
    !create &&
    flags.canWrite &&
    flags.published &&
    !flags.deprecated &&
    !flags.publishing;
  const deprecate =
    !create &&
    flags.canWrite &&
    flags.everPublished &&
    !flags.deprecated &&
    !flags.publishing;
  const editAction = show && flags.canWrite && flags.canAuthor;
  const deleteEntity =
    !create && flags.canWrite && !flags.everPublished && !flags.publishing;
  const cancel = create || edit;
  const lifecycle = publish || openVersion || deprecate;
  const standard = editAction || deleteEntity || cancel;
  const clusters: EntityRecordActionCluster[] = [];
  if (navigation) clusters.push("navigation");
  if (lifecycle) clusters.push("lifecycle");
  if (standard) clusters.push("standard");

  return {
    navigation,
    publish,
    openVersion,
    deprecate,
    edit: editAction,
    deleteEntity,
    cancel,
    lifecycle,
    standard,
    publishFilled: show,
    clusters,
  };
}
