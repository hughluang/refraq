"use client";

import { Button, Group } from "@mantine/core";
import { CanAccess, useNotification, useTranslate } from "@refinedev/core";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useState } from "react";

import { ConfirmActionModal } from "@/components/feedback/ConfirmActionModal";
import { ModuleAction, ModuleId } from "@/features/console/module-identity";
import {
  deleteEntity,
  deprecateEntity,
  openVersion,
  publishVersion,
} from "@/features/entities/api";
import { entityEditHref } from "@/features/entities/entityDetailTab";
import { entityRecordHeaderActions } from "@/features/entities/entityRecordActions";
import { canAuthor, isPublishing } from "@/features/entities/publishStatus";
import type { BusinessEntity } from "@/features/entities/types";
import { useConfirmAction } from "@/hooks/useConfirmAction";
import { ApiError } from "@/lib/api";

type Props = {
  entity: BusinessEntity;
  canWrite: boolean;
  onChanged: () => void;
};

export function EntityRowActions({ entity, canWrite, onChanged }: Props) {
  const t = useTranslate();
  const { open } = useNotification();
  const router = useRouter();
  const [busy, setBusy] = useState(false);
  const publishConfirm = useConfirmAction<true>();
  const openVersionConfirm = useConfirmAction<true>();
  const deprecateConfirm = useConfirmAction<true>();
  const deleteConfirm = useConfirmAction<true>();

  const actions = entityRecordHeaderActions({
    mode: "show",
    canWrite,
    canAuthor: canAuthor(entity),
    publishing: isPublishing(entity),
    deprecated: Boolean(entity.deprecated_at),
    published: entity.current_version?.publish_status === "published",
    everPublished: entity.ever_published,
    hasCurrentVersion: entity.current_version != null,
  });

  const notifyError = (err: unknown, fallback: string) => {
    open?.({
      type: "error",
      message: err instanceof ApiError ? err.detail : fallback,
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

  const confirmOpenVersion = async () => {
    setBusy(true);
    try {
      await openVersion(entity.id, {});
      openVersionConfirm.close();
      open?.({
        type: "success",
        message: t("entities.versions.open.success"),
      });
      router.push(entityEditHref(entity.id));
    } catch (err) {
      notifyError(err, t("entities.versions.open.failed"));
    } finally {
      setBusy(false);
    }
  };

  const confirmDeprecate = async () => {
    setBusy(true);
    try {
      await deprecateEntity(entity.id);
      deprecateConfirm.close();
      open?.({ type: "success", message: t("entities.deprecate.success") });
      onChanged();
    } catch (err) {
      notifyError(err, t("entities.deprecate.failed"));
    } finally {
      setBusy(false);
    }
  };

  const confirmDelete = async () => {
    setBusy(true);
    try {
      await deleteEntity(entity.id);
      deleteConfirm.close();
      open?.({ type: "success", message: t("entities.delete.success") });
      onChanged();
    } catch (err) {
      notifyError(err, t("entities.delete.failed"));
    } finally {
      setBusy(false);
    }
  };

  const visible =
    actions.publish ||
    actions.openVersion ||
    actions.deprecate ||
    actions.edit ||
    actions.deleteEntity;
  if (!visible) return null;

  return (
    <>
      <Group gap="xs" wrap="nowrap">
        {actions.publish ? (
          <Button
            size="xs"
            variant="light"
            disabled={busy}
            onClick={() => publishConfirm.open(true)}
          >
            {t("entities.publish")}
          </Button>
        ) : null}
        {actions.openVersion ? (
          <Button
            size="xs"
            variant="light"
            disabled={busy}
            onClick={() => openVersionConfirm.open(true)}
          >
            {t("entities.versions.open")}
          </Button>
        ) : null}
        {actions.deprecate ? (
          <Button
            size="xs"
            variant="light"
            color="red"
            disabled={busy}
            onClick={() => deprecateConfirm.open(true)}
          >
            {t("entities.deprecate")}
          </Button>
        ) : null}
        {actions.edit ? (
          <Button
            component={Link}
            href={entityEditHref(entity.id)}
            size="xs"
            variant="light"
          >
            {t("actions.edit")}
          </Button>
        ) : null}
        {actions.deleteEntity ? (
          <CanAccess resource={ModuleId.entities} action={ModuleAction.delete}>
            <Button
              size="xs"
              variant="light"
              color="red"
              disabled={busy}
              onClick={() => deleteConfirm.open(true)}
            >
              {t("actions.delete")}
            </Button>
          </CanAccess>
        ) : null}
      </Group>
      <ConfirmActionModal
        opened={publishConfirm.opened}
        onClose={publishConfirm.close}
        title={t("entities.publish.confirmTitle")}
        body={t("entities.publish.confirmBody", { name: entity.name })}
        loading={busy}
        confirmLabel={t("entities.publish")}
        onConfirm={() => void confirmPublish()}
      />
      <ConfirmActionModal
        opened={openVersionConfirm.opened}
        onClose={openVersionConfirm.close}
        title={t("entities.versions.open.confirmTitle")}
        body={t("entities.versions.open.confirmBody", { name: entity.name })}
        loading={busy}
        confirmLabel={t("entities.versions.open")}
        onConfirm={() => void confirmOpenVersion()}
      />
      <ConfirmActionModal
        opened={deprecateConfirm.opened}
        onClose={deprecateConfirm.close}
        title={t("entities.deprecate.confirmTitle")}
        body={t("entities.deprecate.confirmBody", { name: entity.name })}
        confirmColor="red"
        loading={busy}
        confirmLabel={t("entities.deprecate")}
        onConfirm={() => void confirmDeprecate()}
      />
      <ConfirmActionModal
        opened={deleteConfirm.opened}
        onClose={deleteConfirm.close}
        title={t("entities.delete.confirmTitle")}
        body={t("entities.delete.confirmBody", { name: entity.name })}
        confirmColor="red"
        loading={busy}
        confirmLabel={t("actions.delete")}
        onConfirm={() => void confirmDelete()}
      />
    </>
  );
}
