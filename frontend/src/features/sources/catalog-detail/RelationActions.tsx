"use client";

import { useState } from "react";
import { useTranslate } from "@refinedev/core";
import { RowActions, type RowActionVerb } from "@/components/display/RowActions";
import { ConfirmActionModal } from "@/components/feedback/ConfirmActionModal";
import { useConsoleMutation } from "@/components/feedback/useConsoleMutation";
import { deleteJoin, rejectJoin, restoreJoin } from "@/features/sources/api/joins";
import type { CatalogJoin, CatalogObject } from "@/features/sources/types";
import { joinRowActions, joinRowState } from "./joinEdges";
import { relationName } from "./RelationSummary";

export function RelationActions({
  object,
  join,
  writable,
  onInspect,
  onAmend,
  onChanged,
}: {
  object: CatalogObject;
  join: CatalogJoin;
  writable: boolean;
  onInspect: () => void;
  onAmend: () => void;
  onChanged: () => Promise<void>;
}) {
  const t = useTranslate();
  const name = relationName(object, join);
  const policy = joinRowActions(joinRowState(join));
  const [rejectOpen, setRejectOpen] = useState(false);
  const rejection = useConsoleMutation();
  const verbs: RowActionVerb[] = [
    {
      key: "inspect",
      label: t("catalog.joins.inspect"),
      safety: "immediate",
      onClick: onInspect,
    },
  ];

  if (writable && policy.amend) {
    verbs.push({
      key: "amend",
      label: t("catalog.joins.amend"),
      safety: "immediate",
      onClick: onAmend,
    });
  }
  if (writable && policy.restore) {
    verbs.push({
      key: "restore",
      label: t("catalog.joins.restore"),
      action: {
        safety: "immediate",
        recordName: name,
        outcome: t("catalog.joins.restored"),
        execute: () => restoreJoin(join.id),
        onSuccess: onChanged,
      },
    });
  }
  if (writable && policy.reject) {
    verbs.push({
      key: "reject",
      label: t("catalog.joins.reject"),
      color: "red",
      safety: "confirm",
      onClick: () => setRejectOpen(true),
    });
  }
  if (writable && policy.delete) {
    verbs.push({
      key: "delete",
      label: t("catalog.joins.delete"),
      color: "red",
      action: {
        safety: "confirm",
        recordName: name,
        title: t("catalog.joins.deleteConfirm.title", { record: name }),
        consequence: t("catalog.joins.deleteConfirm.body"),
        confirmLabel: t("catalog.joins.delete"),
        confirmColor: "red",
        outcome: t("catalog.joins.deleted"),
        execute: () => deleteJoin(join.id),
        onSuccess: onChanged,
      },
    });
  }

  return (
    <>
      <RowActions recordName={name} verbs={verbs} />
      <ConfirmActionModal
        opened={rejectOpen}
        onClose={() => {
          if (!rejection.submitting) setRejectOpen(false);
        }}
        title={t("catalog.joins.rejectConfirm.title", { record: name })}
        body={t("catalog.joins.rejectConfirm.body", { record: name })}
        confirmLabel={t("catalog.joins.reject")}
        confirmColor="red"
        loading={rejection.submitting}
        onConfirm={() => rejection.run({
          key: "reject",
          safety: "immediate",
          recordName: name,
          outcome: t("catalog.joins.rejected"),
          execute: async () => {
            await rejectJoin(join.id);
            setRejectOpen(false);
          },
          onSuccess: onChanged,
        })}
      />
    </>
  );
}
