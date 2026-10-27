"use client";

import { useNotification, useTranslate } from "@refinedev/core";
import { forwardRef } from "react";

import { replaceEntityTags } from "@/features/entities/api";
import type { EntityTag } from "@/features/entities/types";
import { RecordTagEditor } from "@/features/tags/RecordTagEditor";
import { problemMessage } from "@/lib/problem";

type Draft = {
  tag_ids: string[];
  names: string[];
};

export type EntityTagsControlHandle = {
  flush: () => Draft;
};

type Props = {
  mode: "create" | "show" | "edit";
  entityId?: string;
  tags: EntityTag[];
  tagRevision: number;
  editable: boolean;
  onDraftChange?: (draft: Draft) => void;
  onSaved?: (next: { tags: EntityTag[]; tag_revision: number }) => void;
};

export const EntityTagsControl = forwardRef<EntityTagsControlHandle, Props>(
  function EntityTagsControl(
    { mode, entityId, tags, tagRevision, editable, onDraftChange, onSaved },
    ref,
  ) {
    const t = useTranslate();
    const { open } = useNotification();

    return (
      <RecordTagEditor
        ref={ref}
        title={t("entities.tags.title")}
        description={t(
          mode === "create" ? "entities.tags.createDescription" : "entities.tags.description",
        )}
        emptyLabel={t("entities.tags.empty")}
        removeLabel={(name) => t("entities.tags.remove", { name })}
        saveLabel={mode === "create" ? undefined : t("entities.tags.save")}
        editable={editable}
        tags={tags}
        tagRevision={tagRevision}
        onDraftChange={onDraftChange}
        onSave={
          mode === "create"
            ? undefined
            : async (draft) => {
                if (!entityId) return;
                try {
                  const saved = await replaceEntityTags(entityId, {
                    base_revision: tagRevision,
                    tag_ids: draft.tag_ids,
                    names: draft.names,
                  });
                  onSaved?.(saved);
                  open?.({ type: "success", message: t("entities.tags.saved") });
                } catch (err) {
                  open?.({
                    type: "error",
                    message: problemMessage(t, err, t("entities.tags.failed")),
                  });
                }
              }
        }
      />
    );
  },
);
