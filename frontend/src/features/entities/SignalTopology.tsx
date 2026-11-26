"use client";

import {
  ActionIcon,
  Badge,
  Button,
  Group,
  Stack,
  Switch,
  Text,
  Tooltip,
  UnstyledButton,
} from "@mantine/core";
import { useTranslate } from "@refinedev/core";
import { useCallback, useEffect, useLayoutEffect, useRef, useState } from "react";

import {
  AlertIcon,
  BanIcon,
  EyeIcon,
  EyeOffIcon,
  FilterIcon,
  LockIcon,
  PlusIcon,
  RoleBadgeIcon,
  ShieldLockIcon,
  UserIcon,
  UsersGroupIcon,
} from "@/components/icons";
import {
  parseRuleTree,
  summarizeRuleCompact,
  type HoverTarget,
  type SpecimenPin,
  type WorkbenchIntent,
  type WorkbenchSelection,
} from "@/features/entities/accessWorkbench";
import type {
  AccessGrant,
  AccessProfile,
  AccessRestriction,
  AccessSummary,
} from "@/features/entities/accessTypes";
import { attributeDisplayLabel } from "@/features/entities/entityPresentation";

import classes from "./AccessWorkbench.module.css";

type Props = {
  summary: AccessSummary;
  selection: WorkbenchSelection;
  pin: SpecimenPin;
  hover: HoverTarget;
  busyId: string | null;
  dispatch: (intent: WorkbenchIntent) => Promise<boolean>;
};

type WireSpec = {
  key: string;
  from: string;
  to: string;
  attributed: boolean;
  dimmed: boolean;
  disabled: boolean;
  gate: boolean;
};

type WireLine = WireSpec & { d: string };

function subjectIcon(type: AccessGrant["subject"]["type"]) {
  if (type === "role") return <RoleBadgeIcon size={14} />;
  if (type === "group") return <UsersGroupIcon size={14} />;
  return <UserIcon size={14} />;
}

export function SignalTopology({
  summary,
  selection,
  pin,
  hover,
  busyId,
  dispatch,
}: Props) {
  const t = useTranslate();
  const stageRef = useRef<HTMLDivElement>(null);
  const nodeRefs = useRef(new Map<string, HTMLElement>());
  const [wires, setWires] = useState<WireLine[]>([]);

  const setNodeRef = useCallback((id: string) => {
    return (el: HTMLElement | null) => {
      if (el) nodeRefs.current.set(id, el);
      else nodeRefs.current.delete(id);
    };
  }, []);

  const nameOf = (attributeId: string) => {
    const ladder = summary.ladders.find((item) => item.attribute_id === attributeId);
    return ladder
      ? attributeDisplayLabel({
          name: ladder.attribute_name,
          display_name: ladder.attribute_display_name,
        })
      : attributeId;
  };
  const typeOf = (attributeId: string) =>
    summary.ladders.find((item) => item.attribute_id === attributeId)?.type ?? null;

  const attributedGrantIds = new Set<string>();
  const attributedProfileIds = new Set<string>();
  let gateAttributed = false;

  if (hover?.kind === "cell") {
    for (const gid of hover.sources) attributedGrantIds.add(gid);
    for (const g of summary.grants) {
      if (attributedGrantIds.has(g.id)) attributedProfileIds.add(g.profile_id);
    }
    if (hover.withheld) gateAttributed = true;
  } else if (hover?.kind === "grant") {
    attributedGrantIds.add(hover.id);
    const g = summary.grants.find((item) => item.id === hover.id);
    if (g) attributedProfileIds.add(g.profile_id);
  } else if (hover?.kind === "profile") {
    attributedProfileIds.add(hover.id);
    for (const g of summary.grants) {
      if (g.profile_id === hover.id) attributedGrantIds.add(g.id);
    }
  } else if (hover?.kind === "restriction") {
    gateAttributed = true;
  } else if (selection?.kind === "grant") {
    attributedGrantIds.add(selection.id);
    const g = summary.grants.find((item) => item.id === selection.id);
    if (g) attributedProfileIds.add(g.profile_id);
  } else if (selection?.kind === "profile") {
    attributedProfileIds.add(selection.id);
    for (const g of summary.grants) {
      if (g.profile_id === selection.id) attributedGrantIds.add(g.id);
    }
  } else if (selection?.kind === "restriction") {
    gateAttributed = true;
  }

  const hasAttribution =
    attributedGrantIds.size > 0 || attributedProfileIds.size > 0 || gateAttributed;

  const hasRestrictions = summary.restrictions.length > 0;
  const gateNodeId = hasRestrictions ? "gate:active" : "gate:open";

  const wireSpecs: WireSpec[] = [];
  for (const grant of summary.grants) {
    const attr = attributedGrantIds.has(grant.id);
    wireSpecs.push({
      key: `g:${grant.id}->p:${grant.profile_id}`,
      from: `grant:${grant.id}`,
      to: `profile:${grant.profile_id}`,
      attributed: attr,
      dimmed: hasAttribution && !attr,
      disabled: grant.status !== "active" || grant.broken,
      gate: false,
    });
  }
  for (const profile of summary.profiles) {
    const active = summary.grants.some(
      (g) => g.profile_id === profile.id && g.status === "active" && !g.broken,
    );
    const attr = attributedProfileIds.has(profile.id) || gateAttributed;
    wireSpecs.push({
      key: `p:${profile.id}->${gateNodeId}`,
      from: `profile:${profile.id}`,
      to: gateNodeId,
      attributed: attr,
      dimmed: hasAttribution && !attr,
      disabled: !active,
      gate: hasRestrictions,
    });
  }

  const measureWires = useCallback(() => {
    const stage = stageRef.current;
    if (!stage) return;
    const stageRect = stage.getBoundingClientRect();
    const next: WireLine[] = [];
    for (const spec of wireSpecs) {
      const fromEl = nodeRefs.current.get(spec.from);
      const toEl = nodeRefs.current.get(spec.to);
      if (!fromEl || !toEl) continue;
      const a = fromEl.getBoundingClientRect();
      const b = toEl.getBoundingClientRect();
      const x1 = a.right - stageRect.left + stage.scrollLeft;
      const y1 = a.top + a.height / 2 - stageRect.top;
      const x2 = b.left - stageRect.left + stage.scrollLeft;
      const y2 = b.top + b.height / 2 - stageRect.top;
      const dx = Math.max(24, Math.abs(x2 - x1) * 0.45);
      const d = `M ${x1} ${y1} C ${x1 + dx} ${y1}, ${x2 - dx} ${y2}, ${x2} ${y2}`;
      next.push({ ...spec, d });
    }
    setWires((prev) => {
      if (
        prev.length === next.length &&
        prev.every(
          (w, i) =>
            w.key === next[i]?.key &&
            w.d === next[i]?.d &&
            w.attributed === next[i]?.attributed &&
            w.dimmed === next[i]?.dimmed &&
            w.disabled === next[i]?.disabled &&
            w.gate === next[i]?.gate,
        )
      ) {
        return prev;
      }
      return next;
    });
  }, [wireSpecs]);

  useLayoutEffect(() => {
    measureWires();
  }, [measureWires]);

  useEffect(() => {
    const stage = stageRef.current;
    if (!stage || typeof ResizeObserver === "undefined") return;
    const ro = new ResizeObserver(() => measureWires());
    ro.observe(stage);
    return () => ro.disconnect();
  }, [measureWires]);

  return (
    <div ref={stageRef} className={classes.topologyStage}>
      <svg className={classes.wireLayer} aria-hidden="true">
        {wires.map((w) => {
          const cls = [
            classes.wirePath,
            w.attributed ? classes.wirePathAttributed : "",
            w.dimmed ? classes.wirePathDimmed : "",
            w.disabled ? classes.wirePathDisabled : "",
            w.gate ? classes.wirePathGate : "",
          ]
            .filter(Boolean)
            .join(" ");
          return <path key={w.key} d={w.d} className={cls} />;
        })}
      </svg>

      <div className={classes.topologyColumns}>
        {/* Column 1: Subjects & Grants */}
        <Stack gap="xs">
          <Group justify="space-between" wrap="nowrap">
            <Text size="xs" fw={700} tt="uppercase" c="dimmed">
              {t("entities.access.grants")}
            </Text>
            <Button
              size="compact-xs"
              variant="subtle"
              leftSection={<PlusIcon size={12} />}
              onClick={() => void dispatch({ kind: "select", selection: { kind: "grant_new" } })}
            >
              {t("entities.access.grants.add")}
            </Button>
          </Group>
          {summary.grants.length === 0 ? (
            <UnstyledButton
              className={`${classes.nodeCard} ${classes.nodeCardDisconnected}`}
              onClick={() => void dispatch({ kind: "select", selection: { kind: "grant_new" } })}
            >
              <Text size="xs" c="dimmed">
                {t("entities.access.grants.empty")}
              </Text>
            </UnstyledButton>
          ) : (
            summary.grants.map((grant) => {
              const selected = selection?.kind === "grant" && selection.id === grant.id;
              const attr = attributedGrantIds.has(grant.id);
              const dimmed = hasAttribution && !attr;
              const cardCls = [
                classes.nodeCard,
                selected ? classes.nodeCardSelected : "",
                attr ? classes.nodeCardAttributed : "",
                dimmed ? classes.nodeCardDimmed : "",
                grant.status !== "active" ? classes.nodeCardDisconnected : "",
                grant.broken || grant.subject.missing ? classes.nodeCardBroken : "",
              ]
                .filter(Boolean)
                .join(" ");
              const parsedRule = parseRuleTree(grant.row_rule);
              const isPinnedUser =
                pin.kind === "user" &&
                grant.subject.type === "user" &&
                pin.userId === grant.subject.id;

              return (
                <div
                  key={grant.id}
                  ref={setNodeRef(`grant:${grant.id}`)}
                  className={cardCls}
                  onMouseEnter={() =>
                    void dispatch({ kind: "hover", hover: { kind: "grant", id: grant.id } })
                  }
                  onMouseLeave={() => void dispatch({ kind: "hover", hover: null })}
                  onClick={() =>
                    void dispatch({ kind: "select", selection: { kind: "grant", id: grant.id } })
                  }
                >
                  <Group justify="space-between" wrap="nowrap" gap={6}>
                    <Group gap={6} wrap="nowrap" style={{ minWidth: 0 }}>
                      {subjectIcon(grant.subject.type)}
                      <Text size="sm" fw={600} truncate>
                        {grant.subject.display_name || grant.subject.id}
                      </Text>
                      {grant.locked ? (
                        <Tooltip label={t("entities.access.workbench.lockedGrant")}>
                          <span>
                            <LockIcon size={13} />
                          </span>
                        </Tooltip>
                      ) : null}
                    </Group>
                    <Group gap={4} wrap="nowrap" onClick={(e) => e.stopPropagation()}>
                      {grant.subject.type === "user" && !grant.subject.missing ? (
                        <Tooltip label={t("entities.access.workbench.pinUser")}>
                          <ActionIcon
                            size="xs"
                            variant={isPinnedUser ? "filled" : "subtle"}
                            aria-label={t("entities.access.workbench.pinUser")}
                            onClick={() =>
                              void dispatch({
                                kind: "pin_user",
                                userId: grant.subject.id,
                                displayName: grant.subject.display_name || grant.subject.id,
                              })
                            }
                          >
                            <EyeIcon size={12} />
                          </ActionIcon>
                        </Tooltip>
                      ) : null}
                      {!grant.locked ? (
                        <Switch
                          size="xs"
                          aria-label={t("entities.access.workbench.toggleGrant")}
                          checked={grant.status === "active"}
                          disabled={busyId !== null}
                          onChange={() =>
                            void dispatch({ kind: "toggle_grant_status", grant })
                          }
                        />
                      ) : null}
                    </Group>
                  </Group>
                  <Group gap={4} mt={4} wrap="wrap">
                    {grant.actions.map((action) => (
                      <Badge key={action} size="xs" variant="light">
                        {t(`entities.access.action.${action}`)}
                      </Badge>
                    ))}
                    {parsedRule ? (
                      <Badge size="xs" variant="outline" leftSection={<FilterIcon size={10} />}>
                        {summarizeRuleCompact(parsedRule, t, nameOf, typeOf)}
                      </Badge>
                    ) : null}
                    {(grant.warnings?.length ?? 0) > 0 ? (
                      <Tooltip label={grant.warnings?.[0]?.message ?? ""}>
                        <Badge
                          size="xs"
                          color="yellow"
                          variant="light"
                          leftSection={<AlertIcon size={10} />}
                        >
                          {t("entities.access.workbench.hiddenRuleWarning")}
                        </Badge>
                      </Tooltip>
                    ) : null}
                    {grant.broken || grant.subject.missing ? (
                      <Badge size="xs" color="red" variant="light">
                        {t("entities.access.broken")}
                      </Badge>
                    ) : null}
                  </Group>
                </div>
              );
            })
          )}
        </Stack>

        {/* Column 2: Access Profiles */}
        <Stack gap="xs">
          <Group justify="space-between" wrap="nowrap">
            <Text size="xs" fw={700} tt="uppercase" c="dimmed">
              {t("entities.access.profiles")}
            </Text>
            <Button
              size="compact-xs"
              variant="subtle"
              leftSection={<PlusIcon size={12} />}
              onClick={() => void dispatch({ kind: "select", selection: { kind: "profile_new" } })}
            >
              {t("entities.access.profiles.create")}
            </Button>
          </Group>
          {summary.profiles.length === 0 ? (
            <UnstyledButton
              className={`${classes.nodeCard} ${classes.nodeCardDisconnected}`}
              onClick={() => void dispatch({ kind: "select", selection: { kind: "profile_new" } })}
            >
              <Text size="xs" c="dimmed">
                {t("entities.access.profiles.empty")}
              </Text>
            </UnstyledButton>
          ) : (
            summary.profiles.map((profile: AccessProfile) => {
              const grantCount = summary.grants.filter(
                (g) => g.profile_id === profile.id && g.status === "active" && !g.broken,
              ).length;
              const selected = selection?.kind === "profile" && selection.id === profile.id;
              const attr = attributedProfileIds.has(profile.id);
              const dimmed = hasAttribution && !attr;
              const cardCls = [
                classes.nodeCard,
                selected ? classes.nodeCardSelected : "",
                attr ? classes.nodeCardAttributed : "",
                dimmed ? classes.nodeCardDimmed : "",
                grantCount === 0 ? classes.nodeCardDisconnected : "",
                profile.broken ? classes.nodeCardBroken : "",
              ]
                .filter(Boolean)
                .join(" ");

              return (
                <div
                  key={profile.id}
                  ref={setNodeRef(`profile:${profile.id}`)}
                  className={cardCls}
                  onMouseEnter={() =>
                    void dispatch({ kind: "hover", hover: { kind: "profile", id: profile.id } })
                  }
                  onMouseLeave={() => void dispatch({ kind: "hover", hover: null })}
                  onClick={() =>
                    void dispatch({
                      kind: "select",
                      selection: { kind: "profile", id: profile.id },
                    })
                  }
                >
                  <Group justify="space-between" wrap="nowrap">
                    <Text size="sm" fw={600} truncate>
                      {profile.name}
                    </Text>
                    <Badge size="xs" variant="light" color={grantCount === 0 ? "gray" : "blue"}>
                      {grantCount}
                    </Badge>
                  </Group>
                  <div className={classes.dnaRow} aria-hidden="true">
                    {summary.ladders.map((ladder) => {
                      const col = profile.columns.find((c) => c.attribute_id === ladder.attribute_id);
                      const pipCls = !col
                        ? classes.dnaPipHidden
                        : col.level === "clear"
                          ? classes.dnaPipClear
                          : classes.dnaPipMasked;
                      return (
                        <Tooltip
                          key={ladder.attribute_id}
                          label={`${nameOf(ladder.attribute_id)}: ${col ? col.level : t("entities.access.profiles.notInProfile")}`}
                        >
                          <span className={`${classes.dnaPip} ${pipCls}`} />
                        </Tooltip>
                      );
                    })}
                  </div>
                </div>
              );
            })
          )}
        </Stack>

        {/* Column 3: Guardrail Gate (Access Restrictions) */}
        <Stack gap="xs">
          <Group justify="space-between" wrap="nowrap">
            <Text size="xs" fw={700} tt="uppercase" c="dimmed">
              {t("entities.access.workbench.guardrailGate")}
            </Text>
            <Button
              size="compact-xs"
              variant="subtle"
              leftSection={<PlusIcon size={12} />}
              onClick={() =>
                void dispatch({ kind: "select", selection: { kind: "restriction_new" } })
              }
            >
              {t("entities.access.workbench.addGuardrail")}
            </Button>
          </Group>
          {summary.restrictions.length === 0 ? (
            <div
              ref={setNodeRef("gate:open")}
              className={`${classes.nodeCard} ${classes.nodeCardDisconnected}`}
              onClick={() =>
                void dispatch({ kind: "select", selection: { kind: "restriction_new" } })
              }
            >
              <Group gap={6} wrap="nowrap">
                <ShieldLockIcon size={14} />
                <Text size="xs" c="dimmed">
                  {t("entities.access.workbench.openGate")}
                </Text>
              </Group>
            </div>
          ) : (
            <div ref={setNodeRef("gate:active")}>
              <Stack gap="xs">
                {summary.restrictions.map((item: AccessRestriction) => {
                  const selected =
                    selection?.kind === "restriction" && selection.id === item.id;
                  const cardCls = [
                    classes.nodeCard,
                    selected ? classes.nodeCardSelected : "",
                    gateAttributed ? classes.nodeCardAttributed : "",
                    item.broken ? classes.nodeCardBroken : "",
                  ]
                    .filter(Boolean)
                    .join(" ");
                  const parsedRule = parseRuleTree(item.row_rule);

                  return (
                    <div
                      key={item.id}
                      className={cardCls}
                      onMouseEnter={() =>
                        void dispatch({
                          kind: "hover",
                          hover: { kind: "restriction", id: item.id },
                        })
                      }
                      onMouseLeave={() => void dispatch({ kind: "hover", hover: null })}
                      onClick={() =>
                        void dispatch({
                          kind: "select",
                          selection: { kind: "restriction", id: item.id },
                        })
                      }
                    >
                      <Group justify="space-between" wrap="nowrap" gap={6}>
                        <Group gap={6} wrap="nowrap">
                          <ShieldLockIcon size={14} />
                          <Text size="sm" fw={600}>
                            {t(`entities.access.restrictions.applies.${item.applies_to.mode}`)}
                          </Text>
                        </Group>
                        {item.applies_to.subjects.length > 0 ? (
                          <Badge size="xs" variant="light">
                            {item.applies_to.subjects.length}
                          </Badge>
                        ) : null}
                      </Group>
                      <Group gap={4} mt={4} wrap="wrap">
                        {item.deny_columns.length > 0 ? (
                          <Badge
                            size="xs"
                            color="red"
                            variant="light"
                            leftSection={<EyeOffIcon size={10} />}
                          >
                            {item.deny_columns.map(nameOf).join(", ")}
                          </Badge>
                        ) : null}
                        {item.ceilings.length > 0 ? (
                          <Badge
                            size="xs"
                            color="orange"
                            variant="light"
                            leftSection={<BanIcon size={10} />}
                          >
                            {item.ceilings
                              .map((c) => `${nameOf(c.attribute_id)} ≤ ${c.level}`)
                              .join(", ")}
                          </Badge>
                        ) : null}
                        {parsedRule ? (
                          <Badge size="xs" variant="outline" leftSection={<FilterIcon size={10} />}>
                            {summarizeRuleCompact(parsedRule, t, nameOf, typeOf)}
                          </Badge>
                        ) : null}
                      </Group>
                    </div>
                  );
                })}
              </Stack>
            </div>
          )}
        </Stack>
      </div>
    </div>
  );
}
