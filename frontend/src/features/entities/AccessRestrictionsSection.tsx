"use client";

import { Badge, Button, Collapse, Group, MultiSelect, Stack, Text } from "@mantine/core";
import { useTranslate } from "@refinedev/core";
import { useEffect, useState } from "react";

import { createRestriction, deleteRestriction } from "@/features/entities/accessApi";
import type { AccessSectionId } from "@/features/entities/accessLogic";
import type { AccessRun } from "@/features/entities/accessSession";
import type { AccessSummary } from "@/features/entities/accessTypes";
import { ConfirmActionModal } from "@/components/feedback/ConfirmActionModal";
import { SectionHeader } from "@/components/layout/SectionHeader";

type Props = {
  entityId: string;
  summary: AccessSummary;
  busyId: string | null;
  run: AccessRun;
  focusId: AccessSectionId;
  focusNonce: number;
};

export function AccessRestrictionsSection({
  entityId,
  summary,
  busyId,
  run,
  focusId,
  focusNonce,
}: Props) {
  const t = useTranslate();
  const [open, setOpen] = useState(false);
  const [denyColumns, setDenyColumns] = useState<string[]>([]);
  const [deleteId, setDeleteId] = useState<string | null>(null);
  useEffect(() => {
    if (focusId === "restrictions" && focusNonce > 0) setOpen(true);
  }, [focusId, focusNonce]);

  const creating = busyId === "restriction-create";
  const deleteBusy = deleteId != null && busyId === `restriction-delete:${deleteId}`;
  const nameOf = (id: string) =>
    summary.ladders.find((ladder) => ladder.attribute_id === id)?.attribute_name ?? id;

  return (
    <Stack gap="sm">
      <SectionHeader
        order={4}
        title={t("entities.access.restrictions")}
        description={t("entities.access.restrictions.description")}
        titleExtra={
          summary.restrictions.length > 0 ? (
            <Badge variant="light">{summary.restrictions.length}</Badge>
          ) : null
        }
        actions={
          <Button size="sm" variant="default" onClick={() => setOpen((current) => !current)}>
            {open ? t("entities.access.collapse") : t("entities.access.expand")}
          </Button>
        }
      />
      <Collapse expanded={open}>
        <Stack gap="sm">
          {summary.restrictions.length === 0 ? (
            <Text size="sm" c="dimmed">
              {t("entities.access.restrictions.empty")}
            </Text>
          ) : (
            summary.restrictions.map((item) => (
              <Group key={item.id} justify="space-between">
                <Text size="sm">
                  {t(`entities.access.restrictions.applies.${item.applies_to.mode}`)}
                  {" · "}
                  {item.deny_columns.map(nameOf).join(t("entities.access.summary.actionJoin")) ||
                    "—"}
                  {" · "}
                  {item.actions
                    .map((action) => t(`entities.access.action.${action}`))
                    .join(t("entities.access.summary.actionJoin"))}
                </Text>
                <Button
                  size="xs"
                  color="red"
                  variant="light"
                  disabled={busyId !== null}
                  onClick={() => setDeleteId(item.id)}
                >
                  {t("entities.access.restrictions.delete")}
                </Button>
              </Group>
            ))
          )}
          <MultiSelect
            label={t("entities.access.restrictions.deny")}
            data={summary.ladders.map((ladder) => ({
              value: ladder.attribute_id,
              label: ladder.attribute_name,
            }))}
            value={denyColumns}
            onChange={setDenyColumns}
          />
          <Button
            w="fit-content"
            loading={creating}
            disabled={denyColumns.length === 0 || (busyId !== null && !creating)}
            onClick={() =>
              void run(
                "restriction-create",
                "entities.access.saved.restrictions",
                async () => {
                  await createRestriction(entityId, {
                    applies_to: { mode: "all", subjects: [] },
                    row_rule: null,
                    deny_columns: denyColumns,
                    ceilings: [],
                    actions: ["read"],
                  });
                  setDenyColumns([]);
                },
              )
            }
          >
            {t("entities.access.restrictions.addAll")}
          </Button>
        </Stack>
      </Collapse>
      <ConfirmActionModal
        opened={deleteId !== null}
        onClose={() => setDeleteId(null)}
        title={t("entities.access.restrictions.deleteTitle")}
        body={t("entities.access.restrictions.deleteBody")}
        confirmLabel={t("entities.access.restrictions.delete")}
        confirmColor="red"
        loading={deleteBusy}
        onConfirm={() => {
          if (!deleteId) return;
          void run(
            `restriction-delete:${deleteId}`,
            "entities.access.saved.restrictionRemoved",
            () => deleteRestriction(entityId, deleteId),
          ).then((ok) => {
            if (ok) setDeleteId(null);
          });
        }}
      />
    </Stack>
  );
}
