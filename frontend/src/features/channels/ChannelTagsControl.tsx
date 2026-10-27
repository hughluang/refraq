"use client";

import { useNotification, useTranslate } from "@refinedev/core";
import { forwardRef } from "react";

import { replaceChannelTags } from "@/features/channels/api";
import type { ChannelTag } from "@/features/channels/types";
import { RecordTagEditor } from "@/features/tags/RecordTagEditor";
import { problemMessage } from "@/lib/problem";

type Draft = {
  tag_ids: string[];
  names: string[];
};

export type ChannelTagsControlHandle = {
  flush: () => Draft;
};

type Props = {
  mode: "create" | "show" | "edit";
  channelId?: string;
  tags: ChannelTag[];
  tagRevision: number;
  editable: boolean;
  onDraftChange?: (draft: Draft) => void;
  onSaved?: (next: { tags: ChannelTag[]; tag_revision: number }) => void;
};

export const ChannelTagsControl = forwardRef<ChannelTagsControlHandle, Props>(
  function ChannelTagsControl(
    { mode, channelId, tags, tagRevision, editable, onDraftChange, onSaved },
    ref,
  ) {
    const t = useTranslate();
    const { open } = useNotification();

    return (
      <RecordTagEditor
        ref={ref}
        fieldLabel={t("channels.tags.field")}
        title={t("channels.tags.title")}
        description={t(
          mode === "create" ? "channels.tags.createDescription" : "channels.tags.description",
        )}
        emptyLabel={t("channels.tags.empty")}
        removeLabel={(name) => t("channels.tags.remove", { name })}
        saveLabel={mode === "create" ? undefined : t("channels.tags.save")}
        editable={editable}
        tags={tags}
        tagRevision={tagRevision}
        onDraftChange={onDraftChange}
        onSave={
          mode === "create"
            ? undefined
            : async (draft) => {
                if (!channelId) return;
                try {
                  const saved = await replaceChannelTags(channelId, {
                    base_revision: tagRevision,
                    tag_ids: draft.tag_ids,
                    names: draft.names,
                  });
                  onSaved?.(saved);
                  open?.({ type: "success", message: t("channels.tags.saved") });
                } catch (err) {
                  open?.({
                    type: "error",
                    message: problemMessage(t, err, t("channels.tags.failed")),
                  });
                }
              }
        }
      />
    );
  },
);
