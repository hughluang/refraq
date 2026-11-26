"use client";

import {
  ActionIcon,
  Badge,
  Button,
  Checkbox,
  CloseButton,
  Divider,
  Group,
  MultiSelect,
  NumberInput,
  SegmentedControl,
  Select,
  Stack,
  Switch,
  Text,
  TextInput,
  Tooltip,
} from "@mantine/core";
import { useTranslate } from "@refinedev/core";
import { useEffect, useState } from "react";

import { ConfirmActionModal } from "@/components/feedback/ConfirmActionModal";
import { RecordPicker } from "@/components/form/RecordPicker";
import {
  entityRecordAdapter,
  roleRecordAdapter,
  userGroupRecordAdapter,
  userRecordAdapter,
} from "@/components/form/recordPickerAdapters";
import {
  AlertIcon,
  CloseIcon,
  LockIcon,
  PlusIcon,
  SortAscIcon,
  SortDescIcon,
} from "@/components/icons";
import { getAccessSummary } from "@/features/entities/accessApi";
import {
  GRANT_ACTIONS,
  accessKeyFromName,
  isAccessKey,
  ladderIssueKey,
  levelModeKind,
  levelOptionLabel,
  levelReferrers,
  literalOperand,
  ruleOpLabelKey,
  type RuleOp,
  type RuleOperand,
  type RuleOperandKind,
} from "@/features/entities/accessLogic";
import {
  RULE_DEPTH_MAX,
  RULE_LEAF_MAX,
  availableOperandKinds,
  formatMaskSample,
  formatRelTimeDuration,
  makeDefaultLeaf,
  parseRelTimeDuration,
  parseRuleTree,
  ruleTreeMetrics,
  serializeRuleTree,
  validateLadder,
  type LadderLevel,
  type MaskMode,
  type RuleTreeNode,
  type WorkbenchIntent,
  type WorkbenchSelection,
} from "@/features/entities/accessWorkbench";
import type {
  AccessLadder,
  AccessSubject,
  AccessSummary,
} from "@/features/entities/accessTypes";
import { attributeDisplayLabel, attributeTitle } from "@/features/entities/entityPresentation";
import { useEntryZone } from "@/hooks/useFormatInstant";
import { instantToWall, wallToInstant } from "@/lib/wall-time";

import classes from "./AccessWorkbench.module.css";

type Props = {
  entityId: string;
  summary: AccessSummary;
  selection: Exclude<WorkbenchSelection, null>;
  busyId: string | null;
  lastCopyDropped: { attribute_name: string; reason: string }[];
  dispatch: (intent: WorkbenchIntent) => Promise<boolean>;
};

export function AccessInspector({
  entityId,
  summary,
  selection,
  busyId,
  lastCopyDropped,
  dispatch,
}: Props) {
  const t = useTranslate();
  const close = () => void dispatch({ kind: "select", selection: null });

  return (
    <div className={classes.inspectorFrame}>
      <Group justify="space-between" align="center" mb="sm" wrap="nowrap">
        <Text size="sm" fw={700}>
          {selection.kind === "grant" || selection.kind === "grant_new"
            ? t("entities.access.grants")
            : selection.kind === "ladder"
              ? t("entities.access.ladders")
              : selection.kind === "restriction" || selection.kind === "restriction_new"
                ? t("entities.access.workbench.guardrailGate")
                : t("entities.access.profiles")}
        </Text>
        <ActionIcon
          size="sm"
          variant="subtle"
          aria-label={t("entities.access.collapse")}
          onClick={close}
        >
          <CloseIcon size={14} />
        </ActionIcon>
      </Group>

      {selection.kind === "grant" || selection.kind === "grant_new" ? (
        <GrantInspector
          entityId={entityId}
          summary={summary}
          grantId={selection.kind === "grant" ? selection.id : null}
          initialProfileId={selection.kind === "grant_new" ? selection.profileId : undefined}
          busyId={busyId}
          dispatch={dispatch}
        />
      ) : null}

      {selection.kind === "ladder" ? (
        <LadderInspector
          entityId={entityId}
          summary={summary}
          attributeId={selection.attributeId}
          busyId={busyId}
          dispatch={dispatch}
        />
      ) : null}

      {selection.kind === "profile" ||
      selection.kind === "profile_new" ||
      selection.kind === "profile_copy" ? (
        <ProfileInspector
          entityId={entityId}
          summary={summary}
          mode={selection}
          busyId={busyId}
          lastCopyDropped={lastCopyDropped}
          dispatch={dispatch}
        />
      ) : null}

      {selection.kind === "restriction" || selection.kind === "restriction_new" ? (
        <RestrictionInspector
          entityId={entityId}
          summary={summary}
          restrictionId={selection.kind === "restriction" ? selection.id : null}
          busyId={busyId}
          dispatch={dispatch}
        />
      ) : null}
    </div>
  );
}

/* -------------------------------------------------------------------------- */
/* Shared Nested AND / OR / NOT Row Rule Tree Editor                          */
/* -------------------------------------------------------------------------- */

function RowRuleTree({
  ladders,
  value,
  onChange,
  disabled = false,
}: {
  ladders: AccessLadder[];
  value: RuleTreeNode | null;
  onChange: (next: RuleTreeNode | null) => void;
  disabled?: boolean;
}) {
  const t = useTranslate();
  const metrics = ruleTreeMetrics(value);

  if (!value) {
    return (
      <Group justify="space-between" wrap="nowrap">
        <Text size="xs" c="dimmed">
          {t("entities.access.grants.allRows")}
        </Text>
        {ladders.length > 0 && !disabled ? (
          <Button
            size="compact-xs"
            variant="default"
            leftSection={<PlusIcon size={12} />}
            onClick={() =>
              onChange({
                id: `root_${Date.now()}`,
                kind: "group",
                op: "and",
                children: [makeDefaultLeaf(ladders[0] as AccessLadder)],
              })
            }
          >
            {t("entities.access.grants.limitRows")}
          </Button>
        ) : null}
      </Group>
    );
  }

  return (
    <Stack gap="xs">
      <Group justify="space-between" wrap="nowrap">
        <Badge
          size="xs"
          variant="light"
          color={metrics.overCap ? "red" : "gray"}
        >
          {metrics.leaves} / {RULE_LEAF_MAX} · D{metrics.depth} / {RULE_DEPTH_MAX}
        </Badge>
        {!disabled ? (
          <Button
            size="compact-xs"
            variant="subtle"
            color="red"
            onClick={() => onChange(null)}
          >
            {t("entities.access.grants.allRows")}
          </Button>
        ) : null}
      </Group>
      <RuleNodeView
        ladders={ladders}
        node={value}
        disabled={disabled}
        onChange={onChange}
        onRemove={() => onChange(null)}
      />
    </Stack>
  );
}

function RuleNodeView({
  ladders,
  node,
  disabled,
  onChange,
  onRemove,
}: {
  ladders: AccessLadder[];
  node: RuleTreeNode;
  disabled: boolean;
  onChange: (next: RuleTreeNode) => void;
  onRemove: () => void;
}) {
  const t = useTranslate();

  if (node.kind === "group") {
    return (
      <div className={classes.ruleGroupBox}>
        <Group justify="space-between" wrap="nowrap" gap="xs">
          <SegmentedControl
            size="xs"
            disabled={disabled}
            value={node.op}
            data={[
              { value: "and", label: "AND" },
              { value: "or", label: "OR" },
            ]}
            onChange={(op) => onChange({ ...node, op: op === "or" ? "or" : "and" })}
          />
          {!disabled ? (
            <Group gap={4} wrap="nowrap">
              {ladders.length > 0 ? (
                <Button
                  size="compact-xs"
                  variant="subtle"
                  onClick={() =>
                    onChange({
                      ...node,
                      children: [...node.children, makeDefaultLeaf(ladders[0] as AccessLadder)],
                    })
                  }
                >
                  + {t("entities.access.grants.addCondition")}
                </Button>
              ) : null}
              <Button
                size="compact-xs"
                variant="subtle"
                onClick={() =>
                  onChange({
                    ...node,
                    children: [
                      ...node.children,
                      {
                        id: `grp_${Date.now()}`,
                        kind: "group",
                        op: node.op === "and" ? "or" : "and",
                        children: ladders[0] ? [makeDefaultLeaf(ladders[0])] : [],
                      },
                    ],
                  })
                }
              >
                + ()
              </Button>
              <Button
                size="compact-xs"
                variant="subtle"
                onClick={() =>
                  onChange({
                    id: `not_${Date.now()}`,
                    kind: "not",
                    child: node,
                  })
                }
              >
                NOT
              </Button>
              <CloseButton size="xs" onClick={onRemove} />
            </Group>
          ) : null}
        </Group>
        {node.children.map((child, idx) => (
          <RuleNodeView
            key={child.id}
            ladders={ladders}
            node={child}
            disabled={disabled}
            onChange={(updated) =>
              onChange({
                ...node,
                children: node.children.map((item, i) => (i === idx ? updated : item)),
              })
            }
            onRemove={() => {
              const next = node.children.filter((_, i) => i !== idx);
              if (next.length === 0) onRemove();
              else onChange({ ...node, children: next });
            }}
          />
        ))}
      </div>
    );
  }

  if (node.kind === "not") {
    return (
      <div className={classes.ruleNotBox}>
        <Group justify="space-between" wrap="nowrap">
          <Badge size="xs" color="orange" variant="light">
            NOT
          </Badge>
          {!disabled ? (
            <Button size="compact-xs" variant="subtle" onClick={() => onChange(node.child)}>
              {t("entities.access.grants.removeCondition")}
            </Button>
          ) : null}
        </Group>
        <RuleNodeView
          ladders={ladders}
          node={node.child}
          disabled={disabled}
          onChange={(updated) => onChange({ ...node, child: updated })}
          onRemove={onRemove}
        />
      </div>
    );
  }

  const ladder = ladders.find((l) => l.attribute_id === node.attributeId) ?? ladders[0];
  const ops = (ladder?.operators?.length ? ladder.operators : ["eq", "ne", "is_null"]) as RuleOp[];
  const operandKinds = availableOperandKinds(ladder, node.op);
  const valueType = ladder?.value_type ?? ladder?.type ?? "string";

  const setOperandKind = (nextKind: RuleOperandKind) => {
    let nextOp = node.op;
    if (nextKind === "subject_attr") nextOp = "in";
    else if (nextKind === "subject_id" && !["eq", "ne"].includes(nextOp)) nextOp = "eq";
    else if (nextKind === "rel_time" && !["lt", "lte", "gt", "gte"].includes(nextOp)) {
      nextOp = "gte";
    }
    const nextOperand: RuleOperand =
      nextKind === "subject_id"
        ? { kind: "subject_id" }
        : nextKind === "subject_attr"
          ? {
              kind: "subject_attr",
              key: ladder?.compatible_subject_attributes?.[0]?.key ?? "",
            }
          : nextKind === "rel_time"
            ? { kind: "rel_time", duration: "-P30D" }
            : { kind: "value", value: nextOp === "is_null" ? true : "" };
    onChange({ ...node, op: nextOp, operand: nextOperand });
  };

  return (
    <Stack gap={6} p={6} style={{ border: "1px solid var(--mantine-color-default-border)", borderRadius: 4 }}>
      <Group gap="xs" wrap="wrap" align="flex-end">
        <Select
          size="xs"
          disabled={disabled}
          aria-label={t("entities.access.rule.attr")}
          data={ladders.map((l) => ({
            value: l.attribute_id,
            label: attributeDisplayLabel({
              name: l.attribute_name,
              display_name: l.attribute_display_name,
            }),
          }))}
          value={node.attributeId}
          allowDeselect={false}
          onChange={(attrId) => {
            if (!attrId) return;
            const target = ladders.find((l) => l.attribute_id === attrId);
            onChange({
              ...node,
              attributeId: attrId,
              op: (target?.operators?.[0] as RuleOp) ?? "eq",
              operand: { kind: "value", value: "" },
            });
          }}
        />
        <Select
          size="xs"
          disabled={disabled}
          aria-label={t("entities.access.rule.op")}
          data={ops.map((op) => ({
            value: op,
            label: t(ruleOpLabelKey(op, valueType)),
          }))}
          value={node.op}
          allowDeselect={false}
          onChange={(val) => {
            const nextOp = (val as RuleOp) ?? "eq";
            const legal = availableOperandKinds(ladder, nextOp);
            const nextOperand: RuleOperand = legal.includes(node.operand.kind)
              ? node.operand
              : { kind: "value", value: nextOp === "is_null" ? true : "" };
            onChange({ ...node, op: nextOp, operand: nextOperand });
          }}
        />
        <Select
          size="xs"
          disabled={disabled}
          aria-label={t("entities.access.rule.operand")}
          data={[
            { value: "value", label: t("entities.access.rule.value") },
            ...(ladder?.compatible_subject_attributes?.length
              ? [{ value: "subject_attr", label: t("entities.access.rule.subjectAttr") }]
              : []),
            ...(valueType === "user"
              ? [{ value: "subject_id", label: t("entities.access.rule.subjectId") }]
              : []),
            ...(valueType === "date" || valueType === "timestamp"
              ? [{ value: "rel_time", label: t("entities.access.rule.relTime") }]
              : []),
          ]}
          value={node.operand.kind}
          allowDeselect={false}
          onChange={(val) => setOperandKind((val as RuleOperandKind) ?? "value")}
        />
        {!disabled ? <CloseButton size="xs" onClick={onRemove} /> : null}
      </Group>

      {/* Operand value input */}
      {node.operand.kind === "subject_id" ? null : node.operand.kind === "subject_attr" ? (
        <Select
          size="xs"
          disabled={disabled}
          aria-label={t("entities.access.rule.subjectAttr")}
          data={(ladder?.compatible_subject_attributes ?? []).map((sa) => ({
            value: sa.key,
            label: `${sa.name} (${sa.key})`,
          }))}
          value={node.operand.key || null}
          onChange={(val) =>
            onChange({ ...node, operand: { kind: "subject_attr", key: val ?? "" } })
          }
        />
      ) : node.operand.kind === "rel_time" ? (
        <RelTimeInput
          duration={node.operand.duration}
          allowTimeUnits={valueType === "timestamp"}
          disabled={disabled}
          onChange={(duration) =>
            onChange({ ...node, operand: { kind: "rel_time", duration } })
          }
        />
      ) : node.op === "is_null" ? (
        <SegmentedControl
          size="xs"
          disabled={disabled}
          value={node.operand.value === false ? "false" : "true"}
          data={[
            { value: "true", label: t("entities.access.rule.yes") },
            { value: "false", label: t("entities.access.rule.no") },
          ]}
          onChange={(val) =>
            onChange({ ...node, operand: { kind: "value", value: val === "true" } })
          }
        />
      ) : valueType === "dictionary" && (ladder?.codes?.length ?? 0) > 0 && node.op === "in" ? (
        <MultiSelect
          size="xs"
          disabled={disabled}
          data={ladder?.codes ?? []}
          value={Array.isArray(node.operand.value) ? (node.operand.value as string[]) : []}
          onChange={(vals) => onChange({ ...node, operand: { kind: "value", value: vals } })}
        />
      ) : valueType === "dictionary" && (ladder?.codes?.length ?? 0) > 0 ? (
        <Select
          size="xs"
          disabled={disabled}
          data={ladder?.codes ?? []}
          value={typeof node.operand.value === "string" ? node.operand.value : null}
          onChange={(val) => onChange({ ...node, operand: { kind: "value", value: val ?? "" } })}
        />
      ) : (
        <TextInput
          size="xs"
          disabled={disabled}
          aria-label={t("entities.access.rule.value")}
          value={
            Array.isArray(node.operand.value)
              ? node.operand.value.join(", ")
              : String(node.operand.value ?? "")
          }
          onChange={(e) =>
            onChange({
              ...node,
              operand: { kind: "value", value: literalOperand(node.op, e.currentTarget.value) },
            })
          }
        />
      )}
    </Stack>
  );
}

function RelTimeInput({
  duration,
  allowTimeUnits,
  disabled,
  onChange,
}: {
  duration: string;
  allowTimeUnits: boolean;
  disabled: boolean;
  onChange: (next: string) => void;
}) {
  const t = useTranslate();
  const parsed = parseRelTimeDuration(duration);
  const units = [
    { value: "D", label: t("entities.access.workbench.unitD") },
    { value: "M", label: t("entities.access.workbench.unitM") },
    { value: "Y", label: t("entities.access.workbench.unitY") },
    ...(allowTimeUnits
      ? [
          { value: "H", label: t("entities.access.workbench.unitH") },
          { value: "MI", label: t("entities.access.workbench.unitMI") },
        ]
      : []),
  ];

  return (
    <Group gap="xs" wrap="nowrap">
      <SegmentedControl
        size="xs"
        disabled={disabled}
        value={parsed.direction}
        data={[
          { value: "past", label: t("entities.access.workbench.past") },
          { value: "future", label: t("entities.access.workbench.future") },
        ]}
        onChange={(dir) =>
          onChange(
            formatRelTimeDuration(
              dir === "future" ? "future" : "past",
              parsed.amount,
              parsed.unit,
            ),
          )
        }
      />
      <NumberInput
        size="xs"
        min={1}
        w={72}
        disabled={disabled}
        value={parsed.amount}
        onChange={(val) =>
          onChange(formatRelTimeDuration(parsed.direction, Number(val) || 1, parsed.unit))
        }
      />
      <Select
        size="xs"
        w={84}
        disabled={disabled}
        data={units}
        value={parsed.unit}
        allowDeselect={false}
        onChange={(u) =>
          onChange(
            formatRelTimeDuration(
              parsed.direction,
              parsed.amount,
              (u as typeof parsed.unit) ?? "D",
            ),
          )
        }
      />
    </Group>
  );
}

/* -------------------------------------------------------------------------- */
/* Grant Inspector (Create & Patch + Lock Protection)                         */
/* -------------------------------------------------------------------------- */

function GrantInspector({
  entityId,
  summary,
  grantId,
  initialProfileId,
  busyId,
  dispatch,
}: {
  entityId: string;
  summary: AccessSummary;
  grantId: string | null;
  initialProfileId?: string;
  busyId: string | null;
  dispatch: (intent: WorkbenchIntent) => Promise<boolean>;
}) {
  const t = useTranslate();
  const zone = useEntryZone();
  const existing = grantId ? summary.grants.find((g) => g.id === grantId) ?? null : null;
  const locked = Boolean(existing?.locked);

  const [subjectType, setSubjectType] = useState<"user" | "role" | "group">("user");
  const [subjectId, setSubjectId] = useState<string | null>(null);
  const [profileId, setProfileId] = useState<string | null>(
    existing?.profile_id ?? initialProfileId ?? summary.profiles[0]?.id ?? null,
  );
  const [actions, setActions] = useState<string[]>(existing?.actions ?? ["read"]);
  const [status, setStatus] = useState<"active" | "disabled">(
    existing?.status === "disabled" ? "disabled" : "active",
  );
  const [validUntil, setValidUntil] = useState(
    existing?.valid_until ? instantToWall(existing.valid_until, zone, "T") ?? "" : "",
  );
  const [ruleTree, setRuleTree] = useState<RuleTreeNode | null>(() =>
    existing ? parseRuleTree(existing.row_rule) : null,
  );
  const [confirmRevoke, setConfirmRevoke] = useState(false);

  useEffect(() => {
    setSubjectType("user");
    setSubjectId(null);
    setProfileId(existing?.profile_id ?? initialProfileId ?? summary.profiles[0]?.id ?? null);
    setActions(existing?.actions ?? ["read"]);
    setStatus(existing?.status === "disabled" ? "disabled" : "active");
    setValidUntil(existing?.valid_until ? instantToWall(existing.valid_until, zone, "T") ?? "" : "");
    setRuleTree(existing ? parseRuleTree(existing.row_rule) : null);
  }, [grantId, initialProfileId, existing?.id]);

  const metrics = ruleTreeMetrics(ruleTree);
  const saving = busyId === "grant-save";
  const revoking = busyId === "grant-revoke";

  const subjectAdapter =
    subjectType === "role"
      ? roleRecordAdapter()
      : subjectType === "group"
        ? userGroupRecordAdapter()
        : userRecordAdapter();

  return (
    <Stack gap="sm">
      {locked ? (
        <Group gap={6}>
          <LockIcon size={14} />
          <Text size="xs" c="dimmed">
            {t("entities.access.workbench.lockedGrant")}
          </Text>
        </Group>
      ) : null}

      {existing ? (
        <Group justify="space-between" wrap="nowrap">
          <Text size="sm" fw={600}>
            {existing.subject.display_name || existing.subject.id}
          </Text>
          <Badge size="xs" variant="light">
            {t(`entities.access.subject.${existing.subject.type}`)}
          </Badge>
        </Group>
      ) : (
        <Group grow>
          <Select
            size="xs"
            label={t("entities.access.grants.subjectType")}
            data={[
              { value: "user", label: t("entities.access.subject.user") },
              { value: "group", label: t("entities.access.subject.group") },
              { value: "role", label: t("entities.access.subject.role") },
            ]}
            value={subjectType}
            allowDeselect={false}
            onChange={(val) => {
              setSubjectType((val as "user" | "role" | "group") ?? "user");
              setSubjectId(null);
            }}
          />
          <RecordPicker
            key={subjectType}
            editable
            label={t("entities.access.grants.subject")}
            adapter={subjectAdapter}
            value={subjectId}
            onChange={setSubjectId}
          />
        </Group>
      )}

      <Select
        size="xs"
        label={t("entities.access.grants.scheme")}
        disabled={locked}
        data={summary.profiles.map((p) => ({
          value: p.id,
          label: `${p.name} (${p.columns.length})`,
        }))}
        value={profileId}
        onChange={setProfileId}
      />

      <Checkbox.Group
        label={t("entities.access.grants.actions")}
        value={actions}
        onChange={(next) => {
          if (locked) return;
          if (next.includes("write") && !next.includes("read")) {
            setActions(Array.from(new Set([...next, "read"])));
            return;
          }
          setActions(next);
        }}
      >
        <Group gap="xs" mt={4}>
          {GRANT_ACTIONS.map((action) => (
            <Checkbox
              key={action}
              size="xs"
              disabled={locked}
              value={action}
              label={t(`entities.access.action.${action}`)}
            />
          ))}
        </Group>
      </Checkbox.Group>

      <Group grow align="flex-end">
        <Switch
          size="xs"
          disabled={locked}
          label={t("entities.access.workbench.grantActive")}
          checked={status === "active"}
          onChange={(e) => setStatus(e.currentTarget.checked ? "active" : "disabled")}
        />
        <TextInput
          size="xs"
          disabled={locked}
          label={t("entities.access.grants.validUntil")}
          type="datetime-local"
          value={validUntil}
          onChange={(e) => setValidUntil(e.currentTarget.value)}
        />
      </Group>

      <Divider label={t("entities.access.grants.rule")} labelPosition="left" />

      {(existing?.warnings?.length ?? 0) > 0 ? (
        <Group gap={6}>
          <AlertIcon size={14} />
          <Text size="xs" c="dimmed">
            {existing?.warnings?.[0]?.message}
          </Text>
        </Group>
      ) : null}

      <RowRuleTree
        ladders={summary.ladders}
        value={ruleTree}
        onChange={setRuleTree}
        disabled={locked}
      />

      {!locked ? (
        <Group justify="space-between" mt="xs">
          {existing ? (
            <Button
              size="xs"
              color="red"
              variant="light"
              loading={revoking}
              disabled={busyId !== null && !revoking}
              onClick={() => setConfirmRevoke(true)}
            >
              {t("entities.access.grants.delete")}
            </Button>
          ) : (
            <span />
          )}
          <Button
            size="xs"
            loading={saving}
            disabled={
              (!existing && !subjectId) ||
              !profileId ||
              actions.length === 0 ||
              metrics.overCap ||
              (busyId !== null && !saving)
            }
            onClick={() =>
              void dispatch({
                kind: "mutate",
                busyId: "grant-save",
                savedKey: "entities.access.saved.grants",
                work: async (port) => {
                  const normalizedActions = actions.includes("write")
                    ? Array.from(new Set([...actions, "read"]))
                    : actions;
                  const payloadRule = serializeRuleTree(ruleTree);
                  const instant = validUntil ? wallToInstant(validUntil, zone) : null;
                  if (existing) {
                    await port.patchGrant(entityId, existing.id, {
                      profile_id: profileId as string,
                      row_rule: payloadRule,
                      actions: normalizedActions,
                      status,
                      valid_until: instant,
                    });
                  } else {
                    await port.createGrant(entityId, {
                      subject: { type: subjectType, id: subjectId as string },
                      profile_id: profileId as string,
                      row_rule: payloadRule,
                      actions: normalizedActions,
                      status,
                      valid_until: instant,
                    });
                  }
                },
              })
            }
          >
            {t("entities.access.grants.save")}
          </Button>
        </Group>
      ) : null}

      <ConfirmActionModal
        opened={confirmRevoke}
        onClose={() => setConfirmRevoke(false)}
        title={t("entities.access.grants.revokeTitle")}
        body={t("entities.access.grants.revokeBody", {
          name: existing?.subject.display_name || existing?.subject.id || "",
        })}
        confirmLabel={t("entities.access.grants.delete")}
        confirmColor="red"
        loading={revoking}
        onConfirm={() => {
          if (!existing) return;
          void dispatch({
            kind: "mutate",
            busyId: "grant-revoke",
            savedKey: "entities.access.saved.revoked",
            work: (port) => port.deleteGrant(entityId, existing.id),
          }).then((ok) => {
            if (ok) {
              setConfirmRevoke(false);
              void dispatch({ kind: "select", selection: null });
            }
          });
        }}
      />
    </Stack>
  );
}

/* -------------------------------------------------------------------------- */
/* Ladder Inspector (Reorder Priority + All Mask Parameters + Live Sample)    */
/* -------------------------------------------------------------------------- */

function LadderInspector({
  entityId,
  summary,
  attributeId,
  busyId,
  dispatch,
}: {
  entityId: string;
  summary: AccessSummary;
  attributeId: string;
  busyId: string | null;
  dispatch: (intent: WorkbenchIntent) => Promise<boolean>;
}) {
  const t = useTranslate();
  const ladder = summary.ladders.find((l) => l.attribute_id === attributeId);
  const accepted = ladder?.accepted_masks?.length
    ? ladder.accepted_masks
    : ["null"];

  const [levelKey, setLevelKey] = useState("");
  const [maskType, setMaskType] = useState<string>(accepted[0] ?? "null");
  const [keepFirst, setKeepFirst] = useState(0);
  const [keepLast, setKeepLast] = useState(4);
  const [truncUnit, setTruncUnit] = useState<"year" | "month" | "day">("month");
  const [bucketWidth, setBucketWidth] = useState<number>(100);
  const [issue, setIssue] = useState<string | null>(null);

  useEffect(() => {
    setMaskType(accepted[0] ?? "null");
    setLevelKey("");
    setIssue(null);
  }, [attributeId]);

  if (!ladder) return null;

  const draftMode: MaskMode =
    maskType === "partial"
      ? { type: "partial", keep_first: keepFirst, keep_last: keepLast }
      : maskType === "truncate_date"
        ? { type: "truncate_date", unit: truncUnit }
        : maskType === "bucket"
          ? { type: "bucket", width: Math.max(1, bucketWidth) }
          : { type: maskType as "email" | "hash" | "redact" | "null" };

  const effectiveKey =
    levelKey.trim() ||
    (maskType === "partial"
      ? `partial_${keepFirst}_${keepLast}`
      : maskType === "truncate_date"
        ? `date_${truncUnit}`
        : maskType === "bucket"
          ? `bucket_${Math.max(1, bucketWidth)}`
          : maskType);

  const commitLevels = (nextLevels: LadderLevel[], busyKey: string) =>
    dispatch({
      kind: "mutate",
      busyId: busyKey,
      savedKey: "entities.access.saved.ladders",
      work: async (port) => {
        await port.putLadder(entityId, ladder.attribute_id, nextLevels);
      },
    });

  const moveLevel = (index: number, delta: -1 | 1) => {
    const target = index + delta;
    if (index <= 0 || target <= 0 || target >= ladder.levels.length) return;
    const copy = ladder.levels.map((l) => ({
      key: l.key,
      mode: l.mode as MaskMode,
    }));
    const [item] = copy.splice(index, 1);
    if (!item) return;
    copy.splice(target, 0, item);
    void commitLevels(copy, `ladder-move:${ladder.attribute_id}`);
  };

  return (
    <Stack gap="sm">
      <Stack gap={2}>
        <Text size="sm" fw={600}>
          {attributeTitle({
            name: ladder.attribute_name,
            display_name: ladder.attribute_display_name,
          })}
        </Text>
        <Text size="xs" c="dimmed">
          {ladder.attribute_name} · {ladder.type}
        </Text>
      </Stack>

      <Stack gap="xs">
        {ladder.levels.map((level, index) => {
          const referrers = levelReferrers(
            summary.profiles,
            summary.restrictions,
            ladder.attribute_id,
            level.key,
          );
          const inUse =
            referrers.profileNames.length > 0 || referrers.restrictionCount > 0;
          const label = levelOptionLabel(
            t(`entities.access.mask.${levelModeKind(level.mode)}`),
            level.key,
          );
          return (
            <Group
              key={level.key}
              justify="space-between"
              wrap="nowrap"
              p={6}
              style={{
                border: "1px solid var(--mantine-color-default-border)",
                borderRadius: 4,
              }}
            >
              <Stack gap={1} style={{ minWidth: 0 }}>
                <Group gap={6} wrap="nowrap">
                  <Badge size="xs" variant="light" color={index === 0 ? "blue" : "gray"}>
                    #{index + 1}
                  </Badge>
                  <Text size="xs" fw={600} truncate>
                    {label}
                  </Text>
                </Group>
                <Text size="xs" c="dimmed" truncate>
                  {formatMaskSample(ladder, level.mode as MaskMode)}
                </Text>
              </Stack>
              {index > 0 ? (
                <Group gap={2} wrap="nowrap">
                  <ActionIcon
                    size="xs"
                    variant="subtle"
                    disabled={index <= 1 || busyId !== null}
                    aria-label={t("entities.access.workbench.moveUp")}
                    onClick={() => moveLevel(index, -1)}
                  >
                    <SortAscIcon size={12} />
                  </ActionIcon>
                  <ActionIcon
                    size="xs"
                    variant="subtle"
                    disabled={index >= ladder.levels.length - 1 || busyId !== null}
                    aria-label={t("entities.access.workbench.moveDown")}
                    onClick={() => moveLevel(index, 1)}
                  >
                    <SortDescIcon size={12} />
                  </ActionIcon>
                  <Tooltip
                    label={
                      inUse
                        ? t("entities.access.ladders.inUseBody", {
                            names: referrers.profileNames.join(", "),
                          })
                        : t("entities.access.ladders.remove")
                    }
                  >
                    <span>
                      <ActionIcon
                        size="xs"
                        color="red"
                        variant="subtle"
                        disabled={inUse || busyId !== null}
                        aria-label={t("entities.access.ladders.remove")}
                        onClick={() => {
                          const next = ladder.levels
                            .filter((l) => l.key !== level.key)
                            .map((l) => ({ key: l.key, mode: l.mode as MaskMode }));
                          void commitLevels(next, `ladder-del:${ladder.attribute_id}`);
                        }}
                      >
                        <CloseIcon size={12} />
                      </ActionIcon>
                    </span>
                  </Tooltip>
                </Group>
              ) : null}
            </Group>
          );
        })}
      </Stack>

      <Divider label={t("entities.access.ladders.add")} labelPosition="left" />

      <Select
        size="xs"
        label={t("entities.access.ladders.mask")}
        data={accepted.map((kind) => ({
          value: kind,
          label: t(`entities.access.mask.${kind}`),
        }))}
        value={maskType}
        allowDeselect={false}
        onChange={(val) => setMaskType(val ?? accepted[0] ?? "null")}
      />

      {maskType === "partial" ? (
        <Group grow>
          <NumberInput
            size="xs"
            label={t("entities.access.ladders.keepFirst")}
            min={0}
            max={64}
            value={keepFirst}
            onChange={(val) => setKeepFirst(Number(val) || 0)}
          />
          <NumberInput
            size="xs"
            label={t("entities.access.ladders.keepLast")}
            min={0}
            max={64}
            value={keepLast}
            onChange={(val) => setKeepLast(Number(val) || 0)}
          />
        </Group>
      ) : null}

      {maskType === "truncate_date" ? (
        <SegmentedControl
          size="xs"
          value={truncUnit}
          data={[
            { value: "year", label: t("entities.access.workbench.unitY") },
            { value: "month", label: t("entities.access.workbench.unitM") },
            { value: "day", label: t("entities.access.workbench.unitD") },
          ]}
          onChange={(val) => setTruncUnit((val as "year" | "month" | "day") ?? "month")}
        />
      ) : null}

      {maskType === "bucket" ? (
        <NumberInput
          size="xs"
          label={t("entities.access.workbench.bucketWidth")}
          min={1}
          value={bucketWidth}
          onChange={(val) => setBucketWidth(Number(val) || 10)}
        />
      ) : null}

      <TextInput
        size="xs"
        label={t("entities.access.ladders.levelKey")}
        value={effectiveKey}
        error={issue ? t(ladderIssueKey(issue)) : undefined}
        onChange={(e) => {
          setLevelKey(e.currentTarget.value);
          setIssue(null);
        }}
      />

      <Group justify="space-between" p={6} style={{ background: "var(--mantine-color-default)", borderRadius: 4 }}>
        <Text size="xs" c="dimmed">
          {formatMaskSample(ladder, "clear")} →
        </Text>
        <Text size="xs" fw={600}>
          {formatMaskSample(ladder, draftMode)}
        </Text>
      </Group>

      <Button
        size="xs"
        loading={busyId === `ladder-add:${ladder.attribute_id}`}
        disabled={!isAccessKey(effectiveKey) || busyId !== null}
        onClick={() => {
          const next = [
            ...ladder.levels.map((l) => ({ key: l.key, mode: l.mode as MaskMode })),
            { key: effectiveKey, mode: draftMode },
          ];
          const found = validateLadder(next);
          if (found) {
            setIssue(found);
            return;
          }
          void commitLevels(next, `ladder-add:${ladder.attribute_id}`).then((ok) => {
            if (ok) setLevelKey("");
          });
        }}
      >
        {t("entities.access.ladders.add")}
      </Button>
    </Stack>
  );
}

/* -------------------------------------------------------------------------- */
/* Profile Inspector (Create, Edit, Copy, Delete)                             */
/* -------------------------------------------------------------------------- */

function ProfileInspector({
  entityId,
  summary,
  mode,
  busyId,
  lastCopyDropped,
  dispatch,
}: {
  entityId: string;
  summary: AccessSummary;
  mode:
    | { kind: "profile"; id: string }
    | { kind: "profile_new" }
    | { kind: "profile_copy" };
  busyId: string | null;
  lastCopyDropped: { attribute_name: string; reason: string }[];
  dispatch: (intent: WorkbenchIntent) => Promise<boolean>;
}) {
  const t = useTranslate();
  const existing =
    mode.kind === "profile"
      ? summary.profiles.find((p) => p.id === mode.id) ?? null
      : null;

  const [name, setName] = useState(existing?.name ?? "");
  const [keyInput, setKeyInput] = useState(existing?.key ?? "");
  const [keyTouched, setKeyTouched] = useState(false);
  const [description, setDescription] = useState(existing?.description ?? "");
  const [confirmDelete, setConfirmDelete] = useState(false);

  const [copyEntityId, setCopyEntityId] = useState<string | null>(null);
  const [copyProfiles, setCopyProfiles] = useState<{ value: string; label: string }[]>([]);
  const [copyProfileId, setCopyProfileId] = useState<string | null>(null);

  useEffect(() => {
    setName(existing?.name ?? "");
    setKeyInput(existing?.key ?? "");
    setKeyTouched(false);
    setDescription(existing?.description ?? "");
  }, [mode.kind, existing?.id]);

  if (mode.kind === "profile_copy") {
    const derivedKey = keyTouched ? keyInput.trim() : accessKeyFromName(name);
    return (
      <Stack gap="sm">
        <RecordPicker
          editable
          label={t("entities.access.profiles.copySource")}
          adapter={entityRecordAdapter()}
          excludeIds={[entityId]}
          value={copyEntityId}
          onChange={(val) => {
            setCopyEntityId(val);
            setCopyProfileId(null);
            setCopyProfiles([]);
            if (!val) return;
            void getAccessSummary(val).then((src) =>
              setCopyProfiles(src.profiles.map((p) => ({ value: p.id, label: p.name }))),
            );
          }}
        />
        <Select
          size="xs"
          label={t("entities.access.profiles.copyScheme")}
          data={copyProfiles}
          value={copyProfileId}
          onChange={setCopyProfileId}
        />
        <TextInput
          size="xs"
          label={t("entities.access.profiles.name")}
          value={name}
          onChange={(e) => setName(e.currentTarget.value)}
        />
        <TextInput
          size="xs"
          label={t("entities.access.profiles.key")}
          value={derivedKey}
          onChange={(e) => {
            setKeyTouched(true);
            setKeyInput(e.currentTarget.value);
          }}
        />
        {lastCopyDropped.length > 0 ? (
          <Text size="xs" c="orange">
            {lastCopyDropped.map((d) => `${d.attribute_name} (${d.reason})`).join(", ")}
          </Text>
        ) : null}
        <Button
          size="xs"
          loading={busyId === "profile-copy"}
          disabled={
            !copyEntityId ||
            !copyProfileId ||
            !isAccessKey(derivedKey) ||
            name.trim().length === 0 ||
            busyId !== null
          }
          onClick={() =>
            void dispatch({
              kind: "copy_profile",
              sourceEntityId: copyEntityId as string,
              sourceProfileId: copyProfileId as string,
              key: derivedKey,
              name: name.trim(),
            })
          }
        >
          {t("entities.access.profiles.copyAction")}
        </Button>
      </Stack>
    );
  }

  const effectiveKey = existing
    ? existing.key
    : keyTouched
      ? keyInput.trim()
      : accessKeyFromName(name);
  const inUse = existing
    ? summary.grants.some((g) => g.profile_id === existing.id)
    : false;

  return (
    <Stack gap="sm">
      <TextInput
        size="xs"
        label={t("entities.access.profiles.name")}
        value={name}
        onChange={(e) => setName(e.currentTarget.value)}
      />
      <TextInput
        size="xs"
        label={t("entities.access.profiles.key")}
        disabled={Boolean(existing)}
        value={effectiveKey}
        onChange={(e) => {
          setKeyTouched(true);
          setKeyInput(e.currentTarget.value);
        }}
      />
      <TextInput
        size="xs"
        label={t("common.description")}
        value={description}
        onChange={(e) => setDescription(e.currentTarget.value)}
      />
      <Group justify="space-between">
        {existing ? (
          <Button
            size="xs"
            color="red"
            variant="light"
            disabled={inUse || busyId !== null}
            onClick={() => setConfirmDelete(true)}
          >
            {t("entities.access.profiles.delete")}
          </Button>
        ) : (
          <span />
        )}
        <Button
          size="xs"
          loading={busyId === "profile-save"}
          disabled={
            name.trim().length === 0 ||
            (!existing && !isAccessKey(effectiveKey)) ||
            busyId !== null
          }
          onClick={() =>
            void dispatch({
              kind: "mutate",
              busyId: "profile-save",
              savedKey: "entities.access.saved.profiles",
              work: async (port) => {
                if (existing) {
                  await port.patchProfile(entityId, existing.id, {
                    name: name.trim(),
                    description: description.trim() || null,
                  });
                } else {
                  await port.createProfile(entityId, {
                    key: effectiveKey,
                    name: name.trim(),
                    description: description.trim() || null,
                    columns: [],
                  });
                }
              },
            })
          }
        >
          {existing ? t("entities.access.profiles.save") : t("entities.access.profiles.create")}
        </Button>
      </Group>

      <ConfirmActionModal
        opened={confirmDelete}
        onClose={() => setConfirmDelete(false)}
        title={t("entities.access.profiles.deleteTitle")}
        body={t("entities.access.profiles.deleteBody", { name: existing?.name ?? "" })}
        confirmLabel={t("entities.access.profiles.delete")}
        confirmColor="red"
        loading={busyId === "profile-delete"}
        onConfirm={() => {
          if (!existing) return;
          void dispatch({
            kind: "mutate",
            busyId: "profile-delete",
            savedKey: "entities.access.saved.profileRemoved",
            work: (port) => port.deleteProfile(entityId, existing.id),
          }).then((ok) => {
            if (ok) {
              setConfirmDelete(false);
              void dispatch({ kind: "select", selection: null });
            }
          });
        }}
      />
    </Stack>
  );
}

/* -------------------------------------------------------------------------- */
/* Restriction Inspector (All/Only/Except, Ceilings, Deny Columns, Row Rule)  */
/* -------------------------------------------------------------------------- */

function RestrictionInspector({
  entityId,
  summary,
  restrictionId,
  busyId,
  dispatch,
}: {
  entityId: string;
  summary: AccessSummary;
  restrictionId: string | null;
  busyId: string | null;
  dispatch: (intent: WorkbenchIntent) => Promise<boolean>;
}) {
  const t = useTranslate();
  const existing = restrictionId
    ? summary.restrictions.find((r) => r.id === restrictionId) ?? null
    : null;

  const [mode, setMode] = useState<"all" | "only" | "except">(
    (existing?.applies_to.mode as "all" | "only" | "except") ?? "all",
  );
  const [subjects, setSubjects] = useState<AccessSubject[]>(existing?.applies_to.subjects ?? []);
  const [pickType, setPickType] = useState<"user" | "role" | "group">("user");
  const [pickId, setPickId] = useState<string | null>(null);
  const [actions, setActions] = useState<string[]>(existing?.actions ?? [...GRANT_ACTIONS]);
  const [denyColumns, setDenyColumns] = useState<string[]>(existing?.deny_columns ?? []);
  const [ceilings, setCeilings] = useState<{ attribute_id: string; level: string }[]>(
    existing?.ceilings ?? [],
  );
  const [ruleTree, setRuleTree] = useState<RuleTreeNode | null>(() =>
    existing ? parseRuleTree(existing.row_rule) : null,
  );
  const [confirmDelete, setConfirmDelete] = useState(false);

  useEffect(() => {
    setMode((existing?.applies_to.mode as "all" | "only" | "except") ?? "all");
    setSubjects(existing?.applies_to.subjects ?? []);
    setActions(existing?.actions ?? [...GRANT_ACTIONS]);
    setDenyColumns(existing?.deny_columns ?? []);
    setCeilings(existing?.ceilings ?? []);
    setRuleTree(existing ? parseRuleTree(existing.row_rule) : null);
  }, [restrictionId, existing?.id]);

  const metrics = ruleTreeMetrics(ruleTree);
  const hasPayload =
    denyColumns.length > 0 || ceilings.length > 0 || serializeRuleTree(ruleTree) !== null;
  const scopeValid = mode === "all" || subjects.length > 0;
  const subjectAdapter =
    pickType === "role"
      ? roleRecordAdapter()
      : pickType === "group"
        ? userGroupRecordAdapter()
        : userRecordAdapter();

  return (
    <Stack gap="sm">
      <SegmentedControl
        size="xs"
        value={mode}
        data={[
          { value: "all", label: t("entities.access.restrictions.applies.all") },
          { value: "only", label: t("entities.access.restrictions.applies.only") },
          { value: "except", label: t("entities.access.restrictions.applies.except") },
        ]}
        onChange={(val) => setMode((val as "all" | "only" | "except") ?? "all")}
      />

      {mode !== "all" ? (
        <Stack gap="xs">
          <Group grow align="flex-end">
            <Select
              size="xs"
              data={[
                { value: "user", label: t("entities.access.subject.user") },
                { value: "group", label: t("entities.access.subject.group") },
                { value: "role", label: t("entities.access.subject.role") },
              ]}
              value={pickType}
              allowDeselect={false}
              onChange={(val) => {
                setPickType((val as "user" | "role" | "group") ?? "user");
                setPickId(null);
              }}
            />
            <RecordPicker
              key={pickType}
              editable
              adapter={subjectAdapter}
              value={pickId}
              onChange={(val) => {
                setPickId(val);
                if (!val) return;
                if (!subjects.some((s) => s.type === pickType && s.id === val)) {
                  setSubjects((prev) => [...prev, { type: pickType, id: val }]);
                }
                setPickId(null);
              }}
            />
          </Group>
          <Group gap={4} wrap="wrap">
            {subjects.map((sub) => (
              <Badge
                key={`${sub.type}:${sub.id}`}
                size="sm"
                variant="light"
                rightSection={
                  <CloseButton
                    size="xs"
                    onClick={() =>
                      setSubjects((prev) =>
                        prev.filter((s) => !(s.type === sub.type && s.id === sub.id)),
                      )
                    }
                  />
                }
              >
                {sub.display_name || sub.id}
              </Badge>
            ))}
          </Group>
        </Stack>
      ) : null}

      <Checkbox.Group
        label={t("entities.access.grants.actions")}
        value={actions}
        onChange={setActions}
      >
        <Group gap="xs" mt={4}>
          {GRANT_ACTIONS.map((action) => (
            <Checkbox
              key={action}
              size="xs"
              value={action}
              label={t(`entities.access.action.${action}`)}
            />
          ))}
        </Group>
      </Checkbox.Group>

      <MultiSelect
        size="xs"
        label={t("entities.access.restrictions.deny")}
        data={summary.ladders.map((l) => ({
          value: l.attribute_id,
          label: attributeDisplayLabel({
            name: l.attribute_name,
            display_name: l.attribute_display_name,
          }),
        }))}
        value={denyColumns}
        onChange={setDenyColumns}
      />

      <Divider label={t("entities.access.workbench.ceilings")} labelPosition="left" />

      <Stack gap="xs">
        {ceilings.map((ceiling, idx) => {
          const ladder = summary.ladders.find((l) => l.attribute_id === ceiling.attribute_id);
          return (
            <Group key={`${ceiling.attribute_id}-${idx}`} gap="xs" wrap="nowrap">
              <Select
                size="xs"
                style={{ flex: 1 }}
                data={summary.ladders.map((l) => ({
                  value: l.attribute_id,
                  label: attributeDisplayLabel({
                    name: l.attribute_name,
                    display_name: l.attribute_display_name,
                  }),
                }))}
                value={ceiling.attribute_id}
                allowDeselect={false}
                onChange={(attrId) => {
                  if (!attrId) return;
                  const target = summary.ladders.find((l) => l.attribute_id === attrId);
                  setCeilings((prev) =>
                    prev.map((item, i) =>
                      i === idx
                        ? {
                            attribute_id: attrId,
                            level: target?.levels[0]?.key ?? "clear",
                          }
                        : item,
                    ),
                  );
                }}
              />
              <Select
                size="xs"
                style={{ flex: 1 }}
                data={(ladder?.levels ?? []).map((lvl) => ({
                  value: lvl.key,
                  label: levelOptionLabel(
                    t(`entities.access.mask.${levelModeKind(lvl.mode)}`),
                    lvl.key,
                  ),
                }))}
                value={ceiling.level}
                allowDeselect={false}
                onChange={(lvl) => {
                  if (!lvl) return;
                  setCeilings((prev) =>
                    prev.map((item, i) => (i === idx ? { ...item, level: lvl } : item)),
                  );
                }}
              />
              <CloseButton
                size="xs"
                onClick={() => setCeilings((prev) => prev.filter((_, i) => i !== idx))}
              />
            </Group>
          );
        })}
        {summary.ladders.length > 0 ? (
          <Button
            size="compact-xs"
            variant="subtle"
            w="fit-content"
            leftSection={<PlusIcon size={12} />}
            onClick={() => {
              const unused =
                summary.ladders.find(
                  (l) => !ceilings.some((c) => c.attribute_id === l.attribute_id),
                ) ?? summary.ladders[0];
              if (!unused) return;
              setCeilings((prev) => [
                ...prev,
                {
                  attribute_id: unused.attribute_id,
                  level: unused.levels[unused.levels.length - 1]?.key ?? "clear",
                },
              ]);
            }}
          >
            {t("entities.access.workbench.addCeiling")}
          </Button>
        ) : null}
      </Stack>

      <Divider label={t("entities.access.grants.rule")} labelPosition="left" />

      <RowRuleTree ladders={summary.ladders} value={ruleTree} onChange={setRuleTree} />

      <Group justify="space-between" mt="xs">
        {existing ? (
          <Button
            size="xs"
            color="red"
            variant="light"
            disabled={busyId !== null}
            onClick={() => setConfirmDelete(true)}
          >
            {t("entities.access.restrictions.delete")}
          </Button>
        ) : (
          <span />
        )}
        <Button
          size="xs"
          loading={busyId === "restriction-save"}
          disabled={
            !hasPayload ||
            !scopeValid ||
            actions.length === 0 ||
            metrics.overCap ||
            busyId !== null
          }
          onClick={() =>
            void dispatch({
              kind: "mutate",
              busyId: "restriction-save",
              savedKey: "entities.access.saved.restrictions",
              work: async (port) => {
                const payload = {
                  applies_to: {
                    mode,
                    subjects:
                      mode === "all"
                        ? []
                        : subjects.map((s) => ({ type: s.type, id: s.id })),
                  },
                  row_rule: serializeRuleTree(ruleTree),
                  deny_columns: denyColumns,
                  ceilings,
                  actions,
                };
                if (existing) {
                  await port.patchRestriction(entityId, existing.id, payload);
                } else {
                  await port.createRestriction(entityId, payload);
                }
              },
            })
          }
        >
          {t("entities.access.workbench.saveGuardrail")}
        </Button>
      </Group>

      <ConfirmActionModal
        opened={confirmDelete}
        onClose={() => setConfirmDelete(false)}
        title={t("entities.access.restrictions.deleteTitle")}
        body={t("entities.access.restrictions.deleteBody")}
        confirmLabel={t("entities.access.restrictions.delete")}
        confirmColor="red"
        loading={busyId === "restriction-delete"}
        onConfirm={() => {
          if (!existing) return;
          void dispatch({
            kind: "mutate",
            busyId: "restriction-delete",
            savedKey: "entities.access.saved.restrictionRemoved",
            work: (port) => port.deleteRestriction(entityId, existing.id),
          }).then((ok) => {
            if (ok) {
              setConfirmDelete(false);
              void dispatch({ kind: "select", selection: null });
            }
          });
        }}
      />
    </Stack>
  );
}
