"use client";

import { useCan, useNotification, useTranslate } from "@refinedev/core";
import { useState } from "react";

import { RowActions, type RowActionVerb } from "@/components/display/RowActions";
import { useConsoleNavigation } from "@/components/navigation/useConsoleNavigation";
import { ModuleAction, ModuleId } from "@/features/console/module-identity";
import {
  deleteEntity,
  deprecateEntity,
  openVersion,
  publishVersion,
} from "@/features/entities/api";
import { EntityPublishConfirm } from "@/features/entities/EntityPublishConfirm";
import { entityEditHref } from "@/features/entities/entityDetailTab";
import { canAuthor, isPublishing } from "@/features/entities/publishStatus";
import type { BusinessEntity } from "@/features/entities/types";
import { useConfirmAction } from "@/hooks/useConfirmAction";
import { problemMessage } from "@/lib/problem";

type Props = {
  entity: BusinessEntity;
  canWrite: boolean;
  onChanged: () => void;
};

export function EntityRowActions({ entity, canWrite, onChanged }: Props) {
  const t = useTranslate();
  const { open } = useNotification();
  const { push } = useConsoleNavigation();
  const { data: canDelete } = useCan({
    resource: ModuleId.entities,
    action: ModuleAction.delete,
  });
  const [busy, setBusy] = useState(false);
  const publishConfirm = useConfirmAction<true>();

  const publishing = isPublishing(entity);
  const deprecated = Boolean(entity.deprecated_at);
  const author = canAuthor(entity);
  const published = entity.current_version?.publish_status === "published";
  const recordName = entity.name;

  const notifyError = (err: unknown, fallback: string) => {
    open?.({
      type: "error",
      message: problemMessage(t, err, fallback),
    });
  };

  const confirmPublish = async () => {
    const versionId = entity.current_version?.id;
    if (!versionId) return;
    setBusy(true);
    try {
      const result = await publishVersion(entity.id, versionId);
      publishConfirm.close();
      if (result.job) {
        open?.({ type: "success", message: t("entities.publish.queued") });
      }
      onChanged();
    } catch (err) {
      notifyError(err, t("entities.publish.failed"));
    } finally {
      setBusy(false);
    }
  };

  let publishReason: string | undefined;
  if (!entity.current_version) publishReason = t("entities.actions.noVersion");
  else if (publishing) publishReason = t("entities.actions.publishing");
  else if (deprecated) publishReason = t("entities.actions.deprecated");
  else if (!author) publishReason = t("entities.actions.notDraft");

  let openReason: string | undefined;
  if (publishing) openReason = t("entities.actions.publishing");
  else if (deprecated) openReason = t("entities.actions.deprecated");
  else if (!published) openReason = t("entities.actions.notPublished");

  let deprecateReason: string | undefined;
  if (publishing) deprecateReason = t("entities.actions.publishing");
  else if (deprecated) deprecateReason = t("entities.actions.deprecated");
  else if (!entity.ever_published) deprecateReason = t("entities.actions.neverPublished");

  let editReason: string | undefined;
  if (publishing) editReason = t("entities.actions.publishing");
  else if (deprecated) editReason = t("entities.actions.deprecated");
  else if (!author) editReason = t("entities.actions.notDraft");

  let deleteReason: string | undefined;
  if (publishing) deleteReason = t("entities.actions.publishing");
  else if (entity.ever_published) deleteReason = t("entities.actions.alreadyPublished");

  const verbs: RowActionVerb[] = [
    {
      key: "publish",
      label: t("entities.publish"),
      hidden: !canWrite,
      disabledReason: publishReason,
      safety: "confirm",
      onClick: () => publishConfirm.open(true),
    },
    {
      key: "open",
      label: t("entities.versions.open"),
      hidden: !canWrite,
      disabledReason: openReason,
      action: {
        safety: "confirm",
        recordName,
        title: t("entities.versions.open.confirmTitle"),
        consequence: t("entities.versions.open.confirmBody", { name: recordName }),
        confirmLabel: t("entities.versions.open"),
        outcome: t("entities.versions.open.outcome"),
        execute: async () => {
          await openVersion(entity.id, {});
          push(entityEditHref(entity.id));
        },
      },
    },
    {
      key: "deprecate",
      label: t("entities.deprecate"),
      color: "red",
      hidden: !canWrite,
      disabledReason: deprecateReason,
      action: {
        safety: "confirm",
        recordName,
        title: t("entities.deprecate.confirmTitle"),
        consequence: t("entities.deprecate.consequence"),
        confirmLabel: t("entities.deprecate"),
        confirmColor: "red",
        outcome: t("entities.deprecate.success"),
        execute: () => deprecateEntity(entity.id),
        onSuccess: () => onChanged(),
      },
    },
    {
      key: "edit",
      label: t("actions.edit"),
      hidden: !canWrite,
      disabledReason: editReason,
      safety: "immediate",
      onClick: () => push(entityEditHref(entity.id)),
    },
    {
      key: "delete",
      label: t("actions.delete"),
      color: "red",
      hidden: !canWrite || !canDelete?.can,
      disabledReason: deleteReason,
      action: {
        safety: "confirm",
        recordName,
        title: t("entities.delete.confirmTitle"),
        consequence: t("entities.delete.consequence"),
        confirmLabel: t("actions.delete"),
        confirmColor: "red",
        outcome: t("entities.delete.success"),
        execute: () => deleteEntity(entity.id),
        onSuccess: () => onChanged(),
      },
    },
  ];

  return (
    <>
      <RowActions recordName={recordName} verbs={verbs} />
      <EntityPublishConfirm
        opened={publishConfirm.opened}
        onClose={publishConfirm.close}
        entityId={entity.id}
        versionId={entity.current_version?.id}
        name={entity.name}
        everPublished={entity.ever_published}
        loading={busy}
        onConfirm={() => void confirmPublish()}
      />
    </>
  );
}
