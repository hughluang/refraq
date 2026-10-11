"use client";

import { Button, Stack, Text } from "@mantine/core";
import { useTranslate } from "@refinedev/core";
import { useEffect, useState } from "react";

import { ConfirmActionModal } from "@/components/feedback/ConfirmActionModal";
import {
  previewEntityPublish,
  type IncompatibleWriteNode,
} from "@/features/entities/api";

type PreviewState =
  | { phase: "loading" }
  | { phase: "ready"; nodes: IncompatibleWriteNode[] }
  | { phase: "failed" };

type Props = {
  opened: boolean;
  onClose: () => void;
  entityId: string;
  versionId: string | undefined;
  name: string;
  everPublished: boolean;
  loading: boolean;
  onConfirm: () => void;
};

export function EntityPublishConfirm({
  opened,
  onClose,
  entityId,
  versionId,
  name,
  everPublished,
  loading,
  onConfirm,
}: Props) {
  const t = useTranslate();
  const [preview, setPreview] = useState<PreviewState>({ phase: "loading" });
  const [attempt, setAttempt] = useState(0);
  const [openEpoch, setOpenEpoch] = useState(opened);

  if (opened !== openEpoch) {
    setOpenEpoch(opened);
    setPreview({ phase: "loading" });
  }

  useEffect(() => {
    if (!opened) return;
    if (!versionId) {
      setPreview({ phase: "failed" });
      return;
    }
    let cancelled = false;
    setPreview({ phase: "loading" });
    void previewEntityPublish(entityId, versionId)
      .then((body) => {
        if (!cancelled) {
          setPreview({ phase: "ready", nodes: body.incompatible_write_nodes });
        }
      })
      .catch(() => {
        if (!cancelled) setPreview({ phase: "failed" });
      });
    return () => {
      cancelled = true;
    };
  }, [opened, entityId, versionId, attempt]);

  const retry = () => {
    setPreview({ phase: "loading" });
    setAttempt((current) => current + 1);
  };

  return (
    <ConfirmActionModal
      opened={opened}
      onClose={onClose}
      title={t("entities.publish.confirmTitle")}
      body={t(
        everPublished
          ? "entities.publish.confirmBodySuccessor"
          : "entities.publish.confirmBody",
        { name },
      )}
      loading={loading}
      confirmDisabled={preview.phase !== "ready"}
      confirmLabel={t("entities.publish")}
      onConfirm={onConfirm}
    >
      <PreviewNotice preview={preview} onRetry={retry} />
    </ConfirmActionModal>
  );
}

function PreviewNotice({
  preview,
  onRetry,
}: {
  preview: PreviewState;
  onRetry: () => void;
}) {
  const t = useTranslate();
  if (preview.phase === "loading") {
    return <Text size="sm">{t("entities.publish.previewLoading")}</Text>;
  }
  if (preview.phase === "failed") {
    return (
      <Stack gap="xs">
        <Text size="sm">{t("entities.publish.previewFailed")}</Text>
        <Button size="xs" variant="default" onClick={onRetry} w="fit-content">
          {t("common.retry")}
        </Button>
      </Stack>
    );
  }
  if (preview.nodes.length === 0) {
    return <Text size="sm">{t("entities.publish.noIncompatible")}</Text>;
  }
  return preview.nodes.map((node) => (
    <Text key={`${node.channel_id}-${node.node_id}`} size="sm">
      {node.channel_name} / {node.node_name}: {node.reasons.join(", ")}
    </Text>
  ));
}
