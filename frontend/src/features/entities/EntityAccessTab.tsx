"use client";

import {
  Alert,
  Button,
  Checkbox,
  Group,
  MultiSelect,
  NumberInput,
  Select,
  Stack,
  Table,
  Text,
  TextInput,
  Title,
} from "@mantine/core";
import { useNotification, useTranslate } from "@refinedev/core";
import { useCallback, useEffect, useMemo, useState } from "react";

import {
  copyProfile,
  createGrant,
  createProfile,
  createRestriction,
  deleteGrant,
  deleteProfile,
  deleteRestriction,
  getAccessSummary,
  patchProfile,
  previewAccess,
  putLadder,
} from "@/features/entities/accessApi";
import {
  classifyAccessProblem,
  columnsFromMatrix,
  appendEditorCondition,
  literalOperand,
  matrixColumn,
  presentCell,
  serializeRule,
  validateLadder,
  withheldNames,
  type LadderLevel,
  type RuleLeaf,
  type RuleNode,
  type RuleOp,
} from "@/features/entities/accessLogic";
import type { AccessSummary } from "@/features/entities/accessTypes";
import { PageError } from "@/components/feedback/PageError";
import { listEntities } from "@/features/entities/api";
import { listRoles } from "@/features/roles/api";
import { listSubjectAttributes, listUserGroups } from "@/features/subjects/api";
import { listUsers } from "@/features/users/api";
import { ApiError } from "@/lib/api";

const EMPTY_RULE: RuleNode = { kind: "and", children: [] };
const ACTIONS = ["read", "write", "export", "mcp_query"] as const;
const MASKS = ["partial", "email", "hash", "truncate_date", "bucket", "redact", "null"] as const;

type Option = { value: string; label: string };

type Props = {
  entityId: string;
  canPreviewRows: boolean;
};

function problemText(
  err: unknown,
  t: (key: string, options?: Record<string, unknown>) => string,
): string {
  if (err instanceof ApiError) {
    const kind = classifyAccessProblem(err.code);
    if (kind === "pending") return t("entities.access.pending");
    if (kind === "combination_limit") return t("entities.access.overLimit");
    return err.detail;
  }
  return String(err);
}

function leafOperand(node: RuleLeaf): string {
  const operand = node.operand;
  if (operand.kind === "value") return String(operand.value ?? "");
  if (operand.kind === "subject_attr") return operand.key;
  if (operand.kind === "rel_time") return operand.duration;
  return "";
}

export function EntityAccessTab({ entityId, canPreviewRows }: Props) {
  const t = useTranslate();
  const { open } = useNotification();
  const [summary, setSummary] = useState<AccessSummary | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [optionsError, setOptionsError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [users, setUsers] = useState<Option[]>([]);
  const [roles, setRoles] = useState<Option[]>([]);
  const [groups, setGroups] = useState<Option[]>([]);
  const [subjectAttrs, setSubjectAttrs] = useState<Option[]>([]);
  const [entities, setEntities] = useState<Option[]>([]);
  const [profileKey, setProfileKey] = useState("");
  const [profileName, setProfileName] = useState("");
  const [matrix, setMatrix] = useState<Record<string, Record<string, string>>>({});
  const [maskKey, setMaskKey] = useState<Record<string, string>>({});
  const [maskType, setMaskType] = useState<Record<string, string>>({});
  const [keepFirst, setKeepFirst] = useState<Record<string, number>>({});
  const [keepLast, setKeepLast] = useState<Record<string, number>>({});
  const [subjectType, setSubjectType] = useState<"user" | "role" | "group">("user");
  const [subjectId, setSubjectId] = useState<string | null>(null);
  const [grantProfile, setGrantProfile] = useState<string | null>(null);
  const [grantActions, setGrantActions] = useState<string[]>(["read"]);
  const [validUntil, setValidUntil] = useState("");
  const [ruleAttr, setRuleAttr] = useState<string | null>(null);
  const [ruleOp, setRuleOp] = useState("eq");
  const [ruleKind, setRuleKind] = useState("value");
  const [ruleValue, setRuleValue] = useState("");
  const [rule, setRule] = useState<RuleNode>(EMPTY_RULE);
  const [copyEntity, setCopyEntity] = useState<string | null>(null);
  const [copyProfiles, setCopyProfiles] = useState<Option[]>([]);
  const [copyProfileId, setCopyProfileId] = useState<string | null>(null);
  const [copyKey, setCopyKey] = useState("");
  const [copyName, setCopyName] = useState("");
  const [previewUser, setPreviewUser] = useState<string | null>(null);
  const [includeRows, setIncludeRows] = useState(false);
  const [previewText, setPreviewText] = useState<string | null>(null);
  const [denyColumns, setDenyColumns] = useState<string[]>([]);

  const load = useCallback(async () => {
    const next = await getAccessSummary(entityId);
    setLoadError(null);
    setSummary(next);
    const cells: Record<string, Record<string, string>> = {};
    for (const profile of next.profiles) {
      cells[profile.id] = {};
      for (const ladder of next.ladders) {
        cells[profile.id][ladder.attribute_id] = matrixColumn(
          ladder.attribute_id,
          profile.columns,
        );
      }
    }
    setMatrix(cells);
  }, [entityId]);

  const reload = useCallback(
    () => load().catch((err: unknown) => setLoadError(problemText(err, t))),
    [load, t],
  );

  useEffect(() => {
    void reload();
    const optionsFailed = (err: unknown) => setOptionsError(problemText(err, t));
    setOptionsError(null);
    void listUsers({ limit: 100, offset: 0 })
      .then((page) =>
        setUsers(page.items.map((row) => ({ value: row.id, label: row.display_name || row.account }))),
      )
      .catch(optionsFailed);
    void listRoles({ limit: 100, offset: 0 })
      .then((page) => setRoles(page.items.map((row) => ({ value: row.id, label: row.name }))))
      .catch(optionsFailed);
    void listUserGroups({ limit: 100, offset: 0 })
      .then((page) => setGroups(page.items.map((row) => ({ value: row.id, label: row.name }))))
      .catch(optionsFailed);
    void listSubjectAttributes({ limit: 100, offset: 0 })
      .then((page) => setSubjectAttrs(page.items.map((row) => ({ value: row.key, label: row.name }))))
      .catch(optionsFailed);
    void listEntities({ limit: 100, offset: 0 })
      .then((page) =>
        setEntities(
          page.items
            .filter((row) => row.id !== entityId)
            .map((row) => ({ value: row.id, label: row.name })),
        ),
      )
      .catch(optionsFailed);
  }, [entityId, reload, t]);

  const subjectOptions = subjectType === "role" ? roles : subjectType === "group" ? groups : users;

  const notify = (ok: boolean, detail?: string) => {
    open?.({
      type: ok ? "success" : "error",
      message: ok ? t("entities.access.saved") : detail || t("entities.access.failed"),
    });
  };

  const run = async (work: () => Promise<void>) => {
    setBusy(true);
    try {
      await work();
      await load();
      notify(true);
    } catch (err) {
      const detail = problemText(err, t);
      notify(false, detail);
    } finally {
      setBusy(false);
    }
  };

  const attributeOptions = useMemo(
    () =>
      (summary?.ladders ?? []).map((ladder) => ({
        value: ladder.attribute_id,
        label: ladder.attribute_name,
      })),
    [summary],
  );

  const addLeaf = () => {
    if (!ruleAttr) return;
    const operand =
      ruleKind === "subject_attr"
        ? { kind: "subject_attr" as const, key: ruleValue }
        : ruleKind === "subject_id"
          ? { kind: "subject_id" as const }
          : ruleKind === "rel_time"
            ? { kind: "rel_time" as const, duration: ruleValue }
            : {
                kind: "value" as const,
                value: literalOperand(ruleOp as RuleOp, ruleValue),
              };
    const leaf: RuleLeaf = {
      kind: "leaf",
      op: ruleOp as RuleOp,
      attributeId: ruleAttr,
      operand,
    };
    setRule((current) => appendEditorCondition(current, leaf));
  };

  if (!summary) {
    return loadError ? (
      <PageError message={loadError} onRetry={() => void reload()} />
    ) : (
      <Text>{t("entities.access.loading")}</Text>
    );
  }

  const over =
    summary.views.subjects_over_limit > 0 ||
    summary.views.combinations > summary.views.combination_limit;

  return (
    <Stack gap="lg">
      {loadError ? <Alert color="red">{loadError}</Alert> : null}
      {optionsError ? <Alert color="red">{optionsError}</Alert> : null}
      <Alert color={over || summary.views.state !== "ready" ? "yellow" : "gray"}>
        <Text>
          {t(`entities.access.views.${summary.views.state}`)}{" "}
          {t("entities.access.combinations", {
            count: summary.views.combinations,
            limit: summary.views.combination_limit,
          })}
        </Text>
        {over ? <Text>{t("entities.access.overLimit")}</Text> : null}
      </Alert>

      <Stack gap="xs">
        <Title order={4}>{t("entities.access.ladders")}</Title>
        {summary.ladders.length === 0 ? (
          <Text>{t("entities.access.ladders.empty")}</Text>
        ) : null}
        {summary.ladders.map((ladder) => (
          <Stack key={ladder.attribute_id} gap={4}>
            <Text fw={600}>
              {ladder.attribute_name} ({ladder.type})
            </Text>
            <Text size="sm">
              {ladder.levels.map((level) => level.key).join(" → ")}
            </Text>
            <Group>
              <TextInput
                label={t("entities.access.ladders.levelKey")}
                value={maskKey[ladder.attribute_id] ?? ""}
                onChange={(event) =>
                  setMaskKey((current) => ({
                    ...current,
                    [ladder.attribute_id]: event.currentTarget.value,
                  }))
                }
              />
              <Select
                label={t("entities.access.ladders.mask")}
                data={MASKS.map((mask) => ({
                  value: mask,
                  label: t(`entities.access.mask.${mask}`),
                }))}
                value={maskType[ladder.attribute_id] ?? "null"}
                onChange={(value) =>
                  setMaskType((current) => ({
                    ...current,
                    [ladder.attribute_id]: value ?? "null",
                  }))
                }
              />
              {(maskType[ladder.attribute_id] ?? "null") === "partial" ? (
                <>
                  <NumberInput
                    label={t("entities.access.ladders.keepFirst")}
                    value={keepFirst[ladder.attribute_id] ?? 0}
                    min={0}
                    max={64}
                    onChange={(value) =>
                      setKeepFirst((current) => ({
                        ...current,
                        [ladder.attribute_id]: Number(value) || 0,
                      }))
                    }
                  />
                  <NumberInput
                    label={t("entities.access.ladders.keepLast")}
                    value={keepLast[ladder.attribute_id] ?? 4}
                    min={0}
                    max={64}
                    onChange={(value) =>
                      setKeepLast((current) => ({
                        ...current,
                        [ladder.attribute_id]: Number(value) || 0,
                      }))
                    }
                  />
                </>
              ) : null}
              <Button
                size="sm"
                mt={24}
                loading={busy}
                onClick={() => {
                  const key = (maskKey[ladder.attribute_id] ?? "").trim();
                  const kind = maskType[ladder.attribute_id] ?? "null";
                  const mode: LadderLevel["mode"] =
                    kind === "partial"
                      ? {
                          type: "partial",
                          keep_first: keepFirst[ladder.attribute_id] ?? 0,
                          keep_last: keepLast[ladder.attribute_id] ?? 4,
                        }
                      : kind === "truncate_date"
                        ? { type: "truncate_date", unit: "month" }
                        : kind === "bucket"
                          ? { type: "bucket", width: 10 }
                          : { type: kind as "null" };
                  const levels: LadderLevel[] = [
                    ...ladder.levels.map((level) =>
                      level.mode === "clear"
                        ? { key: level.key, mode: "clear" as const }
                        : {
                            key: level.key,
                            mode: level.mode as Exclude<LadderLevel["mode"], "clear">,
                          },
                    ),
                    { key, mode },
                  ];
                  const issue = validateLadder(levels);
                  if (issue) {
                    notify(false, t("entities.access.ladders.invalid"));
                    return;
                  }
                  void run(() => putLadder(entityId, ladder.attribute_id, levels).then(() => undefined));
                }}
              >
                {t("entities.access.ladders.add")}
              </Button>
            </Group>
          </Stack>
        ))}
      </Stack>

      <Stack gap="xs">
        <Title order={4}>{t("entities.access.profiles")}</Title>
        <Group>
          <TextInput
            label={t("entities.access.profiles.key")}
            value={profileKey}
            onChange={(event) => setProfileKey(event.currentTarget.value)}
          />
          <TextInput
            label={t("entities.access.profiles.name")}
            value={profileName}
            onChange={(event) => setProfileName(event.currentTarget.value)}
          />
          <Button
            mt={24}
            loading={busy}
            onClick={() =>
              void run(async () => {
                await createProfile(entityId, {
                  key: profileKey.trim(),
                  name: profileName.trim(),
                  columns: [],
                });
                setProfileKey("");
                setProfileName("");
              })
            }
          >
            {t("entities.access.profiles.create")}
          </Button>
        </Group>
        {summary.profiles.length > 0 ? (
          <Table.ScrollContainer minWidth={640}>
            <Table>
              <Table.Thead>
                <Table.Tr>
                  <Table.Th>{t("entities.access.profiles.column")}</Table.Th>
                  {summary.profiles.map((profile) => (
                    <Table.Th key={profile.id}>{profile.name}</Table.Th>
                  ))}
                </Table.Tr>
              </Table.Thead>
              <Table.Tbody>
                {summary.ladders.map((ladder) => (
                  <Table.Tr key={ladder.attribute_id}>
                    <Table.Td>{ladder.attribute_name}</Table.Td>
                    {summary.profiles.map((profile) => (
                      <Table.Td key={profile.id}>
                        <Select
                          data={[
                            { value: "", label: t("entities.access.profiles.notInProfile") },
                            ...ladder.levels.map((level) => ({
                              value: level.key,
                              label: level.key,
                            })),
                          ]}
                          value={matrix[profile.id]?.[ladder.attribute_id] ?? ""}
                          onChange={(value) =>
                            setMatrix((current) => ({
                              ...current,
                              [profile.id]: {
                                ...(current[profile.id] ?? {}),
                                [ladder.attribute_id]: value ?? "",
                              },
                            }))
                          }
                        />
                      </Table.Td>
                    ))}
                  </Table.Tr>
                ))}
                <Table.Tr>
                  <Table.Td />
                  {summary.profiles.map((profile) => (
                    <Table.Td key={profile.id}>
                      <Group>
                        <Button
                          size="xs"
                          loading={busy}
                          onClick={() =>
                            void run(() =>
                              patchProfile(entityId, profile.id, {
                                columns: columnsFromMatrix(
                                  summary.ladders.map((ladder) => ladder.attribute_id),
                                  matrix[profile.id] ?? {},
                                ),
                              }).then(() => undefined),
                            )
                          }
                        >
                          {t("entities.access.profiles.save")}
                        </Button>
                        <Button
                          size="xs"
                          color="red"
                          variant="light"
                          loading={busy}
                          onClick={() =>
                            void run(() => deleteProfile(entityId, profile.id))
                          }
                        >
                          {t("entities.access.profiles.delete")}
                        </Button>
                      </Group>
                    </Table.Td>
                  ))}
                </Table.Tr>
              </Table.Tbody>
            </Table>
          </Table.ScrollContainer>
        ) : null}
        <Title order={5}>{t("entities.access.profiles.copy")}</Title>
        <Group>
          <Select
            label={t("entities.access.profiles.copySource")}
            data={entities}
            value={copyEntity}
            onChange={(value) => {
              setCopyEntity(value);
              setCopyProfileId(null);
              setCopyProfiles([]);
              if (!value) return;
              void getAccessSummary(value)
                .then((source) =>
                  setCopyProfiles(
                    source.profiles.map((profile) => ({
                      value: profile.id,
                      label: profile.name,
                    })),
                  ),
                )
                .catch((err: unknown) => setOptionsError(problemText(err, t)));
            }}
          />
          <Select
            label={t("entities.access.profiles.column")}
            data={copyProfiles}
            value={copyProfileId}
            onChange={setCopyProfileId}
          />
          <TextInput
            label={t("entities.access.profiles.key")}
            value={copyKey}
            onChange={(event) => setCopyKey(event.currentTarget.value)}
          />
          <TextInput
            label={t("entities.access.profiles.name")}
            value={copyName}
            onChange={(event) => setCopyName(event.currentTarget.value)}
          />
          <Button
            mt={24}
            loading={busy}
            disabled={!copyEntity || !copyProfileId}
            onClick={() =>
              void run(() =>
                copyProfile(entityId, {
                  source_entity_id: copyEntity as string,
                  source_profile_id: copyProfileId as string,
                  key: copyKey.trim(),
                  name: copyName.trim(),
                }).then(() => undefined),
              )
            }
          >
            {t("entities.access.profiles.copy")}
          </Button>
        </Group>
      </Stack>

      <Stack gap="xs">
        <Title order={4}>{t("entities.access.grants")}</Title>
        {summary.grants.map((grant) => (
          <Group key={grant.id} justify="space-between">
            <Text>
              {grant.subject.display_name || grant.subject.id} · {grant.actions.join(", ")}
              {grant.valid_until ? ` · ${grant.valid_until}` : ""}
              {grant.broken ? ` · ${t("entities.access.broken")}` : ""}
            </Text>
            <Button
              size="xs"
              color="red"
              variant="light"
              onClick={() => void run(() => deleteGrant(entityId, grant.id))}
            >
              {t("entities.access.grants.delete")}
            </Button>
          </Group>
        ))}
        <Group align="end">
          <Select
            label={t("entities.access.grants.subjectType")}
            data={[
              { value: "user", label: t("entities.access.subject.user") },
              { value: "group", label: t("entities.access.subject.group") },
              { value: "role", label: t("entities.access.subject.role") },
            ]}
            value={subjectType}
            onChange={(value) =>
              setSubjectType((value as "user" | "role" | "group") ?? "user")
            }
          />
          <Select
            label={t("entities.access.grants.subject")}
            data={subjectOptions}
            value={subjectId}
            onChange={setSubjectId}
            searchable
          />
          <Select
            label={t("entities.access.profiles.column")}
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
        <Checkbox.Group value={grantActions} onChange={setGrantActions}>
          <Group>
            {ACTIONS.map((action) => (
              <Checkbox key={action} value={action} label={t(`entities.access.action.${action}`)} />
            ))}
          </Group>
        </Checkbox.Group>
        <Text fw={600}>{t("entities.access.grants.rule")}</Text>
        <Group align="end">
          <Select
            label={t("entities.access.rule.attr")}
            data={attributeOptions}
            value={ruleAttr}
            onChange={setRuleAttr}
          />
          <Select
            label={t("entities.access.rule.op")}
            data={["eq", "ne", "lt", "lte", "gt", "gte", "in", "is_null", "contains"].map(
              (op) => ({ value: op, label: op }),
            )}
            value={ruleOp}
            onChange={(value) => setRuleOp(value ?? "eq")}
          />
          <Select
            label={t("entities.access.rule.operand")}
            data={[
              { value: "value", label: t("entities.access.rule.value") },
              { value: "subject_attr", label: t("entities.access.rule.subjectAttr") },
              { value: "subject_id", label: t("entities.access.rule.subjectId") },
              { value: "rel_time", label: t("entities.access.rule.relTime") },
            ]}
            value={ruleKind}
            onChange={(value) => setRuleKind(value ?? "value")}
          />
          {ruleKind === "subject_attr" ? (
            <Select data={subjectAttrs} value={ruleValue} onChange={(value) => setRuleValue(value ?? "")} />
          ) : ruleKind === "subject_id" ? null : (
            <TextInput value={ruleValue} onChange={(event) => setRuleValue(event.currentTarget.value)} />
          )}
          <Button onClick={addLeaf}>{t("entities.access.grants.addCondition")}</Button>
        </Group>
        <Text size="sm">
          {rule.children
            .map((node) => `${node.attributeId} ${node.op} ${leafOperand(node)}`)
            .join(" AND ") || t("entities.access.grants.allRows")}
        </Text>
        <Button
          loading={busy}
          disabled={!subjectId || !grantProfile}
          onClick={() =>
            void run(async () => {
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

      <Stack gap="xs">
        <Title order={4}>{t("entities.access.restrictions")}</Title>
        {summary.restrictions.map((item) => (
          <Group key={item.id} justify="space-between">
            <Text>
              {item.applies_to.mode} · {item.actions.join(", ")}
            </Text>
            <Button
              size="xs"
              color="red"
              variant="light"
              onClick={() => void run(() => deleteRestriction(entityId, item.id))}
            >
              {t("entities.access.restrictions.delete")}
            </Button>
          </Group>
        ))}
        <MultiSelect
          label={t("entities.access.restrictions.deny")}
          data={attributeOptions}
          value={denyColumns}
          onChange={setDenyColumns}
        />
        <Button
          loading={busy}
          disabled={denyColumns.length === 0}
          onClick={() =>
            void run(() =>
              createRestriction(entityId, {
                applies_to: { mode: "all", subjects: [] },
                row_rule: null,
                deny_columns: denyColumns,
                ceilings: [],
                actions: ["read"],
              }).then(() => undefined),
            )
          }
        >
          {t("entities.access.restrictions.addAll")}
        </Button>
      </Stack>

      <Stack gap="xs">
        <Title order={4}>{t("entities.access.preview")}</Title>
        <Group>
          <Select
            label={t("entities.access.subject.user")}
            data={users}
            value={previewUser}
            onChange={setPreviewUser}
            searchable
          />
          <Checkbox
            mt={28}
            label={t("entities.access.preview.includeRows")}
            checked={includeRows && canPreviewRows}
            disabled={!canPreviewRows}
            onChange={(event) => setIncludeRows(event.currentTarget.checked)}
          />
          <Button
            mt={24}
            loading={busy}
            disabled={!previewUser}
            onClick={() =>
              void (async () => {
                setBusy(true);
                try {
                  const result = await previewAccess(entityId, {
                    subject: { type: "user", id: previewUser as string },
                    include_rows: includeRows && canPreviewRows,
                  });
                  const names = result.schema.attributes
                    .map((attribute) => {
                      const marks = [
                        attribute.presentation?.row_varying
                          ? t("entities.access.cell.rowVarying")
                          : "",
                        attribute.presentation?.may_be_withheld
                          ? t("entities.access.cell.withheld")
                          : "",
                      ].filter(Boolean);
                      return marks.length ? `${attribute.name} (${marks.join(", ")})` : attribute.name;
                    })
                    .join(", ");
                  const rows = (result.rows?.items ?? [])
                    .map((row) => {
                      const held = withheldNames(row, result.schema.withheld_field);
                      const sources = row.__sources;
                      return result.schema.attributes
                        .map((attribute) => {
                          const cell = presentCell({
                            name: attribute.name,
                            value: row[attribute.name],
                            withheld: held,
                            referenceHidden: false,
                          });
                          const source =
                            sources && typeof sources === "object"
                              ? (sources as Record<string, unknown>)[attribute.name]
                              : undefined;
                          const label =
                            cell.kind === "withheld"
                              ? t("entities.access.cell.withheld")
                              : cell.kind === "empty"
                                ? t("entities.access.cell.empty")
                                : cell.text;
                          return source ? `${label} [${String(source)}]` : label;
                        })
                        .join(" | ");
                    })
                    .join("\n");
                  setPreviewText(`${names}${rows ? `\n${rows}` : ""}`);
                } catch (err) {
                  setPreviewText(problemText(err, t));
                } finally {
                  setBusy(false);
                }
              })()
            }
          >
            {t("entities.access.preview.run")}
          </Button>
        </Group>
        {previewText ? <Text style={{ whiteSpace: "pre-wrap" }}>{previewText}</Text> : null}
      </Stack>
    </Stack>
  );
}
