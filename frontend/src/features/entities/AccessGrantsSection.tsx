"use client";

import {
  Button,
  Checkbox,
  Collapse,
  Group,
  Select,
  Stack,
  Table,
  Text,
  TextInput,
} from "@mantine/core";
import { useTranslate } from "@refinedev/core";
import { useEffect, useState } from "react";

import { createGrant, deleteGrant } from "@/features/entities/accessApi";
import {
  GRANT_ACTIONS,
  RULE_OPS,
  describeStoredRule,
  literalOperand,
  operandText,
  ruleEditorHint,
  ruleLeafPhrase,
  ruleOpLabelKey,
  ruleOperandKinds,
  serializeRule,
  type AccessSectionId,
  type RuleLeaf,
  type RuleNode,
  type RuleOp,
  type RuleOperandKind,
} from "@/features/entities/accessLogic";
import type { AccessOption, AccessRun } from "@/features/entities/accessSession";
import type { AccessSummary } from "@/features/entities/accessTypes";
import { ConfirmActionModal } from "@/components/feedback/ConfirmActionModal";
import { EmptyState } from "@/components/feedback/EmptyState";
import { SectionHeader } from "@/components/layout/SectionHeader";
import { formatInstant } from "@/lib/datetime";

const EMPTY_RULE: RuleNode = { kind: "and", children: [] };

type Props = {
  entityId: string;
  summary: AccessSummary;
  users: AccessOption[];
  roles: AccessOption[];
  groups: AccessOption[];
  subjectAttrs: AccessOption[];
  busyId: string | null;
  run: AccessRun;
  focusId: AccessSectionId;
  focusNonce: number;
};

export function AccessGrantsSection({
  entityId,
  summary,
  users,
  roles,
  groups,
  subjectAttrs,
  busyId,
  run,
  focusId,
  focusNonce,
}: Props) {
  const t = useTranslate();
  const [open, setOpen] = useState(false);
  const [limitRows, setLimitRows] = useState(false);
  const [subjectType, setSubjectType] = useState<"user" | "role" | "group">("user");
  const [subjectId, setSubjectId] = useState<string | null>(null);
  const [grantProfile, setGrantProfile] = useState<string | null>(null);
  const [grantActions, setGrantActions] = useState<string[]>(["read"]);
  const [validUntil, setValidUntil] = useState("");
  const [ruleAttr, setRuleAttr] = useState<string | null>(null);
  const [ruleOp, setRuleOp] = useState<RuleOp>("eq");
  const [ruleKind, setRuleKind] = useState<RuleOperandKind>("value");
  const [ruleValue, setRuleValue] = useState("");
  const [rule, setRule] = useState<RuleNode>(EMPTY_RULE);
  const [revokeId, setRevokeId] = useState<string | null>(null);

  const subjectOptions = subjectType === "role" ? roles : subjectType === "group" ? groups : users;
  const attributeName = (id: string) =>
    summary.ladders.find((ladder) => ladder.attribute_id === id)?.attribute_name ?? id;
  const attributeType = (id: string) =>
    summary.ladders.find((ladder) => ladder.attribute_id === id)?.type ?? null;
  const names = { attributeName, attributeType };
  const creating = busyId === "grant-create";
  const revoking = summary.grants.find((grant) => grant.id === revokeId) ?? null;
  const revokeBusy = revokeId != null && busyId === `grant-delete:${revokeId}`;
  const columnType = ruleAttr ? attributeType(ruleAttr) : null;
  const operandKinds = ruleOperandKinds(ruleOp, columnType);
  const hintKey = ruleEditorHint(ruleOp, columnType);
  const operandReady =
    ruleKind === "subject_id" || (ruleKind === "value" && ruleOp === "is_null")
      ? ruleValue === "true" || ruleValue === "false" || ruleKind === "subject_id"
      : ruleValue.trim().length > 0;
  const operandLabels: Record<RuleOperandKind, string> = {
    value: t("entities.access.rule.value"),
    subject_attr: t("entities.access.rule.subjectAttr"),
    subject_id: t("entities.access.rule.subjectId"),
    rel_time: t("entities.access.rule.relTime"),
  };

  const keepLegalOperand = (op: RuleOp, attributeTypeName: string | null, kind: RuleOperandKind) => {
    if (ruleOperandKinds(op, attributeTypeName).includes(kind)) return;
    setRuleKind("value");
    setRuleValue(op === "is_null" ? "true" : "");
  };

  useEffect(() => {
    if (focusId === "grants" && focusNonce > 0) setOpen(true);
  }, [focusId, focusNonce]);

  const addLeaf = () => {
    if (!ruleAttr || !operandReady) return;
    if (!ruleOperandKinds(ruleOp, attributeType(ruleAttr)).includes(ruleKind)) return;
    const operand =
      ruleKind === "subject_attr"
        ? { kind: "subject_attr" as const, key: ruleValue }
        : ruleKind === "subject_id"
          ? { kind: "subject_id" as const }
          : ruleKind === "rel_time"
            ? { kind: "rel_time" as const, duration: ruleValue.trim() }
            : { kind: "value" as const, value: literalOperand(ruleOp, ruleValue) };
    const leaf: RuleLeaf = {
      kind: "leaf",
      op: ruleOp,
      attributeId: ruleAttr,
      operand,
    };
    setRule((current) => ({ kind: "and", children: [...current.children, leaf] }));
    setRuleValue("");
  };

  return (
    <Stack gap="sm">
      <SectionHeader
        order={4}
        title={t("entities.access.grants")}
        description={t("entities.access.grants.description")}
        actions={
          <Button size="sm" variant="default" onClick={() => setOpen((current) => !current)}>
            {open ? t("entities.access.collapse") : t("entities.access.grants.add")}
          </Button>
        }
      />
      {summary.grants.length === 0 ? (
        <EmptyState message={t("entities.access.grants.empty")} />
      ) : (
        <Table.ScrollContainer minWidth={720}>
          <Table>
            <Table.Thead>
              <Table.Tr>
                <Table.Th>{t("entities.access.grants.subject")}</Table.Th>
                <Table.Th>{t("entities.access.grants.scheme")}</Table.Th>
                <Table.Th>{t("entities.access.grants.actions")}</Table.Th>
                <Table.Th>{t("entities.access.grants.rows")}</Table.Th>
                <Table.Th>{t("entities.access.grants.validUntil")}</Table.Th>
                <Table.Th />
              </Table.Tr>
            </Table.Thead>
            <Table.Tbody>
              {summary.grants.map((grant) => {
                const profile = summary.profiles.find((item) => item.id === grant.profile_id);
                return (
                  <Table.Tr key={grant.id}>
                    <Table.Td>
                      {grant.subject.display_name || grant.subject.id}
                      {grant.broken || grant.subject.missing
                        ? ` · ${t("entities.access.broken")}`
                        : ""}
                    </Table.Td>
                    <Table.Td>{profile?.name ?? grant.profile_id}</Table.Td>
                    <Table.Td>
                      {grant.actions
                        .map((action) => t(`entities.access.action.${action}`))
                        .join(t("entities.access.summary.actionJoin"))}
                    </Table.Td>
                    <Table.Td>
                      {describeStoredRule(t, grant.row_rule, names)}
                    </Table.Td>
                    <Table.Td>
                      {grant.valid_until
                        ? formatInstant(grant.valid_until)
                        : t("entities.access.grants.noExpiry")}
                    </Table.Td>
                    <Table.Td>
                      <Button
                        size="xs"
                        color="red"
                        variant="light"
                        disabled={busyId !== null}
                        onClick={() => setRevokeId(grant.id)}
                      >
                        {t("entities.access.grants.delete")}
                      </Button>
                    </Table.Td>
                  </Table.Tr>
                );
              })}
            </Table.Tbody>
          </Table>
        </Table.ScrollContainer>
      )}
      <Collapse expanded={open}>
        <Stack gap="sm">
          <Group align="flex-end">
            <Select
              label={t("entities.access.grants.subjectType")}
              data={[
                { value: "user", label: t("entities.access.subject.user") },
                { value: "group", label: t("entities.access.subject.group") },
                { value: "role", label: t("entities.access.subject.role") },
              ]}
              value={subjectType}
              onChange={(value) => {
                setSubjectType((value as "user" | "role" | "group") ?? "user");
                setSubjectId(null);
              }}
            />
            <Select
              label={t("entities.access.grants.subject")}
              data={subjectOptions}
              value={subjectId}
              onChange={setSubjectId}
              searchable
            />
            <Select
              label={t("entities.access.grants.scheme")}
              data={summary.profiles.map((profile) => ({
                value: profile.id,
                label: profile.name,
              }))}
              value={grantProfile}
              onChange={setGrantProfile}
            />
            <TextInput
              label={t("entities.access.grants.validUntil")}
              type="datetime-local"
              value={validUntil}
              onChange={(event) => setValidUntil(event.currentTarget.value)}
            />
          </Group>
          <Checkbox.Group
            value={grantActions}
            onChange={(next) => {
              if (next.includes("write") && !next.includes("read")) {
                setGrantActions(Array.from(new Set([...next, "read"])));
                return;
              }
              setGrantActions(next);
            }}
          >
            <Group>
              {GRANT_ACTIONS.map((action) => (
                <Checkbox
                  key={action}
                  value={action}
                  label={t(`entities.access.action.${action}`)}
                />
              ))}
            </Group>
          </Checkbox.Group>
          {grantActions.includes("write") ? (
            <Text size="sm" c="dimmed">
              {t("entities.access.grants.writeImpliesRead")}
            </Text>
          ) : null}
          <Text fw={600}>{t("entities.access.grants.rule")}</Text>
          {rule.children.length === 0 ? (
            <Text size="sm">{t("entities.access.grants.allRows")}</Text>
          ) : (
            <Stack gap={4}>
              {rule.children.map((leaf, index) => (
                <Group key={`${leaf.attributeId}-${index}`} gap="xs">
                  <Text size="sm">
                    {ruleLeafPhrase({
                      attribute: attributeName(leaf.attributeId),
                      operator: t(ruleOpLabelKey(leaf.op, attributeType(leaf.attributeId))),
                      operand:
                        leaf.operand.kind === "subject_id"
                          ? t("entities.access.rule.subjectId")
                          : operandText(leaf.operand),
                    })}
                  </Text>
                  <Button
                    size="xs"
                    variant="subtle"
                    onClick={() =>
                      setRule((current) => ({
                        kind: "and",
                        children: current.children.filter((_, item) => item !== index),
                      }))
                    }
                  >
                    {t("entities.access.grants.removeCondition")}
                  </Button>
                </Group>
              ))}
            </Stack>
          )}
          {limitRows || rule.children.length > 0 ? null : (
            <Button size="sm" variant="default" w="fit-content" onClick={() => setLimitRows(true)}>
              {t("entities.access.grants.limitRows")}
            </Button>
          )}
          {limitRows || rule.children.length > 0 ? (
            <Stack gap="xs">
              <Group align="flex-end">
                <Select
                  label={t("entities.access.rule.attr")}
                  data={summary.ladders.map((ladder) => ({
                    value: ladder.attribute_id,
                    label: ladder.attribute_name,
                  }))}
                  value={ruleAttr}
                  onChange={(value) => {
                    setRuleAttr(value);
                    keepLegalOperand(ruleOp, value ? attributeType(value) : null, ruleKind);
                  }}
                />
                <Select
                  label={t("entities.access.rule.op")}
                  data={RULE_OPS.map((op) => ({
                    value: op,
                    label: t(ruleOpLabelKey(op, columnType)),
                  }))}
                  value={ruleOp}
                  onChange={(value) => {
                    const next = (value as RuleOp) ?? "eq";
                    setRuleOp(next);
                    keepLegalOperand(next, columnType, ruleKind);
                  }}
                />
                <Select
                  label={t("entities.access.rule.operand")}
                  data={operandKinds.map((kind) => ({
                    value: kind,
                    label: operandLabels[kind],
                  }))}
                  value={ruleKind}
                  onChange={(value) => {
                    const next = operandKinds.includes(value as RuleOperandKind)
                      ? (value as RuleOperandKind)
                      : "value";
                    setRuleKind(next);
                    setRuleValue(next === "subject_id" || ruleOp === "is_null" ? "true" : "");
                  }}
                />
                {ruleKind === "subject_id" ? null : ruleKind === "subject_attr" ? (
                  <Select
                    data={subjectAttrs}
                    value={ruleValue || null}
                    onChange={(value) => setRuleValue(value ?? "")}
                    aria-label={t("entities.access.rule.subjectAttr")}
                  />
                ) : ruleOp === "is_null" && ruleKind === "value" ? (
                  <Select
                    data={[
                      { value: "true", label: t("entities.access.rule.yes") },
                      { value: "false", label: t("entities.access.rule.no") },
                    ]}
                    value={ruleValue || null}
                    onChange={(value) => setRuleValue(value ?? "")}
                    aria-label={t("entities.access.rule.value")}
                  />
                ) : (
                  <TextInput
                    aria-label={t("entities.access.rule.value")}
                    value={ruleValue}
                    onChange={(event) => setRuleValue(event.currentTarget.value)}
                  />
                )}
                <Button
                  disabled={!ruleAttr || !operandReady || !operandKinds.includes(ruleKind)}
                  onClick={addLeaf}
                >
                  {t("entities.access.grants.addCondition")}
                </Button>
              </Group>
              {hintKey ? (
                <Text size="sm" c="dimmed">
                  {t(hintKey)}
                </Text>
              ) : null}
            </Stack>
          ) : null}
          <Button
            w="fit-content"
            loading={creating}
            disabled={
              !subjectId ||
              !grantProfile ||
              grantActions.length === 0 ||
              (busyId !== null && !creating)
            }
            onClick={() =>
              void run("grant-create", "entities.access.saved.grants", async () => {
                const actions = grantActions.includes("write")
                  ? Array.from(new Set([...grantActions, "read"]))
                  : grantActions;
                await createGrant(entityId, {
                  subject: { type: subjectType, id: subjectId as string },
                  profile_id: grantProfile as string,
                  row_rule: serializeRule(rule),
                  actions,
                  valid_until: validUntil ? new Date(validUntil).toISOString() : null,
                });
                setRule(EMPTY_RULE);
              })
            }
          >
            {t("entities.access.grants.save")}
          </Button>
        </Stack>
      </Collapse>
      <ConfirmActionModal
        opened={revoking !== null}
        onClose={() => setRevokeId(null)}
        title={t("entities.access.grants.revokeTitle")}
        body={t("entities.access.grants.revokeBody", {
          name: revoking?.subject.display_name || revoking?.subject.id || "",
        })}
        confirmLabel={t("entities.access.grants.delete")}
        confirmColor="red"
        loading={revokeBusy}
        onConfirm={() => {
          if (!revokeId) return;
          void run(`grant-delete:${revokeId}`, "entities.access.saved.revoked", () =>
            deleteGrant(entityId, revokeId),
          ).then((ok) => {
            if (ok) setRevokeId(null);
          });
        }}
      />
    </Stack>
  );
}
