"use client";

import { Badge, Button, Collapse, Group, NumberInput, Select, Stack, Text, TextInput } from "@mantine/core";
import { useTranslate } from "@refinedev/core";
import { useEffect, useState } from "react";

import { putLadder } from "@/features/entities/accessApi";
import {
  MASK_KINDS,
  isAccessKey,
  ladderIssueKey,
  laddersClearOnly,
  levelModeKind,
  levelOptionLabel,
  levelReferrers,
  validateLadder,
  type AccessSectionId,
  type LadderLevel,
} from "@/features/entities/accessLogic";
import type { AccessRun } from "@/features/entities/accessSession";
import type { AccessLevel, AccessSummary } from "@/features/entities/accessTypes";
import { ConfirmActionModal } from "@/components/feedback/ConfirmActionModal";
import { EmptyState } from "@/components/feedback/EmptyState";
import { SectionHeader } from "@/components/layout/SectionHeader";

type RemoveTarget = {
  attributeId: string;
  attributeName: string;
  levelKey: string;
  levelLabel: string;
};

type Props = {
  entityId: string;
  summary: AccessSummary;
  busyId: string | null;
  run: AccessRun;
  focusId: AccessSectionId;
  focusNonce: number;
};

function maskMode(
  kind: (typeof MASK_KINDS)[number],
  keepFirst: number,
  keepLast: number,
): Exclude<LadderLevel["mode"], "clear"> {
  switch (kind) {
    case "partial":
      return { type: "partial", keep_first: keepFirst, keep_last: keepLast };
    case "truncate_date":
      return { type: "truncate_date", unit: "month" };
    case "bucket":
      return { type: "bucket", width: 10 };
    case "email":
    case "hash":
    case "redact":
    case "null":
      return { type: kind };
  }
}

function asLadderLevels(levels: AccessLevel[], extra?: LadderLevel): LadderLevel[] {
  const mapped = levels.map((level) =>
    level.mode === "clear"
      ? { key: level.key, mode: "clear" as const }
      : { key: level.key, mode: level.mode as Exclude<LadderLevel["mode"], "clear"> },
  );
  return extra ? [...mapped, extra] : mapped;
}

export function AccessLaddersSection({
  entityId,
  summary,
  busyId,
  run,
  focusId,
  focusNonce,
}: Props) {
  const t = useTranslate();
  const clearOnly = laddersClearOnly(summary.ladders);
  const [sectionOpen, setSectionOpen] = useState(() => !laddersClearOnly(summary.ladders));
  const [openAttribute, setOpenAttribute] = useState<string | null>(null);
  const [levelKey, setLevelKey] = useState("");
  const [maskType, setMaskType] = useState<(typeof MASK_KINDS)[number]>("null");
  const [keepFirst, setKeepFirst] = useState(0);
  const [keepLast, setKeepLast] = useState(4);
  const [issue, setIssue] = useState<string | null>(null);
  const [removeTarget, setRemoveTarget] = useState<RemoveTarget | null>(null);

  const referrers = removeTarget
    ? levelReferrers(
        summary.profiles,
        summary.restrictions,
        removeTarget.attributeId,
        removeTarget.levelKey,
      )
    : { profileNames: [], restrictionCount: 0 };
  const blocked = referrers.profileNames.length > 0 || referrers.restrictionCount > 0;
  const removeBusy =
    removeTarget != null && busyId === `ladder-remove:${removeTarget.attributeId}`;

  useEffect(() => {
    if (!laddersClearOnly(summary.ladders)) setSectionOpen(true);
  }, [summary]);

  useEffect(() => {
    if (focusId === "ladders" && focusNonce > 0) setSectionOpen(true);
  }, [focusId, focusNonce]);

  return (
    <Stack gap="sm">
      <SectionHeader
        order={4}
        title={t("entities.access.ladders")}
        description={t("entities.access.ladders.description")}
        actions={
          clearOnly ? (
            <Button size="sm" variant="default" onClick={() => setSectionOpen((open) => !open)}>
              {sectionOpen ? t("entities.access.collapse") : t("entities.access.expand")}
            </Button>
          ) : null
        }
      />
      {summary.ladders.length === 0 ? (
        <EmptyState message={t("entities.access.ladders.empty")} />
      ) : !sectionOpen ? (
        <Text size="sm" c="dimmed">
          {t("entities.access.ladders.clearOnly")}
        </Text>
      ) : (
        summary.ladders.map((ladder) => {
          const open = openAttribute === ladder.attribute_id;
          const adding = busyId === `ladder-add:${ladder.attribute_id}`;
          return (
            <Stack key={ladder.attribute_id} gap="xs">
              <Group justify="space-between" align="flex-start" wrap="wrap">
                <Stack gap={2}>
                  <Text fw={600}>{ladder.attribute_name}</Text>
                  <Text size="xs" c="dimmed">
                    {ladder.type}
                  </Text>
                </Stack>
                <Group gap="xs" wrap="wrap">
                  {ladder.levels.map((level, index) => {
                    const label = levelOptionLabel(
                      t(`entities.access.mask.${levelModeKind(level.mode)}`),
                      level.key,
                    );
                    const usedBy = levelReferrers(
                      summary.profiles,
                      summary.restrictions,
                      ladder.attribute_id,
                      level.key,
                    );
                    return (
                      <Group key={level.key} gap={4}>
                        {index > 0 ? (
                          <Text size="sm" c="dimmed">
                            →
                          </Text>
                        ) : null}
                        <Badge variant="light" color={level.key === "clear" ? "gray" : "blue"}>
                          {label}
                        </Badge>
                        {usedBy.profileNames.length > 0 ? (
                          <Text size="xs" c="dimmed">
                            {t("entities.access.ladders.usedBy", {
                              names: usedBy.profileNames.join(
                                t("entities.access.summary.actionJoin"),
                              ),
                            })}
                          </Text>
                        ) : null}
                        {level.key === "clear" ? null : (
                          <Button
                            size="xs"
                            variant="subtle"
                            color="red"
                            disabled={busyId !== null}
                            onClick={() =>
                              setRemoveTarget({
                                attributeId: ladder.attribute_id,
                                attributeName: ladder.attribute_name,
                                levelKey: level.key,
                                levelLabel: label,
                              })
                            }
                          >
                            {t("entities.access.ladders.remove")}
                          </Button>
                        )}
                      </Group>
                    );
                  })}
                </Group>
                <Button
                  size="sm"
                  variant="default"
                  onClick={() => {
                    setIssue(null);
                    setLevelKey("");
                    setOpenAttribute(open ? null : ladder.attribute_id);
                  }}
                >
                  {open ? t("entities.access.collapse") : t("entities.access.ladders.add")}
                </Button>
              </Group>
              <Collapse expanded={open}>
                <Stack gap="xs">
                  <Text size="sm" c="dimmed">
                    {t("entities.access.ladders.description")}
                  </Text>
                  <Group align="flex-end">
                    <TextInput
                      label={t("entities.access.ladders.levelKey")}
                      description={t("entities.access.ladders.keyHint")}
                      value={levelKey}
                      error={issue ? t(ladderIssueKey(issue)) : undefined}
                      onChange={(event) => {
                        setLevelKey(event.currentTarget.value);
                        setIssue(null);
                      }}
                    />
                    <Select
                      label={t("entities.access.ladders.mask")}
                      data={MASK_KINDS.map((mask) => ({
                        value: mask,
                        label: t(`entities.access.mask.${mask}`),
                      }))}
                      value={maskType}
                      onChange={(value) =>
                        setMaskType(
                          MASK_KINDS.includes(value as (typeof MASK_KINDS)[number])
                            ? (value as (typeof MASK_KINDS)[number])
                            : "null",
                        )
                      }
                    />
                    {maskType === "partial" ? (
                      <>
                        <NumberInput
                          label={t("entities.access.ladders.keepFirst")}
                          value={keepFirst}
                          min={0}
                          max={64}
                          onChange={(value) => setKeepFirst(Number(value) || 0)}
                        />
                        <NumberInput
                          label={t("entities.access.ladders.keepLast")}
                          value={keepLast}
                          min={0}
                          max={64}
                          onChange={(value) => setKeepLast(Number(value) || 0)}
                        />
                      </>
                    ) : null}
                    <Button
                      loading={adding}
                      disabled={!isAccessKey(levelKey.trim()) || (busyId !== null && !adding)}
                      onClick={() => {
                        const key = levelKey.trim();
                        const levels = asLadderLevels(ladder.levels, {
                          key,
                          mode: maskMode(maskType, keepFirst, keepLast),
                        });
                        const found = validateLadder(levels);
                        if (found) {
                          setIssue(found);
                          return;
                        }
                        void run(
                          `ladder-add:${ladder.attribute_id}`,
                          "entities.access.saved.ladders",
                          () => putLadder(entityId, ladder.attribute_id, levels).then(() => undefined),
                        ).then((ok) => {
                          if (!ok) return;
                          setLevelKey("");
                          setIssue(null);
                          setOpenAttribute(null);
                        });
                      }}
                    >
                      {t("entities.access.ladders.add")}
                    </Button>
                  </Group>
                </Stack>
              </Collapse>
            </Stack>
          );
        })
      )}
      <ConfirmActionModal
        opened={removeTarget !== null}
        onClose={() => setRemoveTarget(null)}
        title={t("entities.access.ladders.removeTitle")}
        confirmLabel={t("entities.access.ladders.remove")}
        confirmColor="red"
        confirmDisabled={blocked}
        loading={removeBusy}
        body={
          removeTarget
            ? blocked
              ? [
                  referrers.profileNames.length
                    ? t("entities.access.ladders.inUseBody", {
                        names: referrers.profileNames.join(t("entities.access.summary.actionJoin")),
                      })
                    : "",
                  referrers.restrictionCount
                    ? t("entities.access.ladders.inUseRestrictions")
                    : "",
                ]
                  .filter(Boolean)
                  .join(" ")
              : t("entities.access.ladders.removeBody", {
                  column: removeTarget.attributeName,
                  level: removeTarget.levelLabel,
                })
            : ""
        }
        onConfirm={() => {
          if (!removeTarget || blocked) return;
          const ladder = summary.ladders.find(
            (item) => item.attribute_id === removeTarget.attributeId,
          );
          if (!ladder) return;
          const levels = asLadderLevels(
            ladder.levels.filter((level) => level.key !== removeTarget.levelKey),
          );
          const found = validateLadder(levels);
          if (found) {
            setIssue(found);
            return;
          }
          void run(`ladder-remove:${removeTarget.attributeId}`, "entities.access.saved.ladders", () =>
            putLadder(entityId, removeTarget.attributeId, levels).then(() => undefined),
          ).then((ok) => {
            if (ok) setRemoveTarget(null);
          });
        }}
      />
    </Stack>
  );
}
