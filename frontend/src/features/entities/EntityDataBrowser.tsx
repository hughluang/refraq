"use client";

import {
  Alert,
  Button,
  Group,
  Loader,
  Select,
  Skeleton,
  Stack,
  Table,
  Text,
} from "@mantine/core";
import { useGetIdentity, useTranslate } from "@refinedev/core";
import { useEffect, useRef, useState } from "react";

import { ListPager } from "@/components/display/ListPager";
import { EmptyState } from "@/components/feedback/EmptyState";
import { listAccountGroups } from "@/features/account/api";
import { loadDataSchema, queryDataRows } from "@/features/entities/accessApi";
import {
  classifyAccessProblem,
  isMaskedPresentation,
  narrowBody,
  presentCell,
  withheldNames,
} from "@/features/entities/accessLogic";
import type { DataSchema } from "@/features/entities/accessTypes";
import { ApiError } from "@/lib/api";
import { pageToOffset } from "@/lib/pagination";
import { problemMessage } from "@/lib/problem";
import type { CurrentUser } from "@/providers/session-store";

const PAGE_SIZE = 50;
const SKELETON_ROWS = 4;
const SKELETON_COLUMNS = 3;

type Props = {
  tableName: string;
  physicalHidden: boolean;
  active: boolean;
};

type ViewAs = "none" | "user" | "role" | "group";
/** null: not listing groups (or list failed; failure text is in `message`). */
type GroupsLoad = "loading" | "ready" | null;

function SkeletonRows() {
  return (
    <Table.ScrollContainer minWidth={480}>
      <Table>
        <Table.Tbody aria-busy="true">
          {Array.from({ length: SKELETON_ROWS }, (_, row) => (
            <Table.Tr key={row}>
              {Array.from({ length: SKELETON_COLUMNS }, (_, col) => (
                <Table.Td key={col}>
                  <Skeleton height={14} radius="sm" />
                </Table.Td>
              ))}
            </Table.Tr>
          ))}
        </Table.Tbody>
      </Table>
    </Table.ScrollContainer>
  );
}

export function EntityDataBrowser({ tableName, physicalHidden, active }: Props) {
  const t = useTranslate();
  const { data: me } = useGetIdentity<CurrentUser>();
  const roleId = me?.role_id ?? null;
  const [kind, setKind] = useState<ViewAs>("none");
  const [groupId, setGroupId] = useState<string | null>(null);
  const [groups, setGroups] = useState<{ id: string; name: string }[]>([]);
  const [groupsLoad, setGroupsLoad] = useState<GroupsLoad>(null);
  const [schema, setSchema] = useState<DataSchema | null>(null);
  const [rows, setRows] = useState<Record<string, unknown>[]>([]);
  const [total, setTotal] = useState(0);
  const [page, setPage] = useState(1);
  const [message, setMessage] = useState<string | null>(null);
  const [pending, setPending] = useState(false);
  const [busy, setBusy] = useState(false);
  const [reloadNonce, setReloadNonce] = useState(0);
  const requestSeq = useRef(0);
  const groupsSeq = useRef(0);
  const tRef = useRef(t);
  tRef.current = t;

  const narrowKey = kind === "role" ? (roleId ?? "") : kind === "group" ? (groupId ?? "") : kind;
  const selectionReady = kind === "role" || kind === "group" ? narrowKey !== "" : true;

  const explain = (err: unknown) => {
    const translate = tRef.current;
    if (!(err instanceof ApiError)) return String(err);
    if (err.code === "ENTITY_NOT_FOUND") return translate("entities.data.noGrant");
    if (err.code === "ENTITY_ACCESS_INVALID") return translate("entities.data.narrowRejected");
    const problem = classifyAccessProblem(err.code);
    if (problem === "pending") return translate("entities.data.pending");
    if (problem === "combination_limit") return translate("entities.access.overLimit");
    return problemMessage(translate, err, err.detail);
  };

  const clearResults = (nextBusy: boolean) => {
    requestSeq.current += 1;
    setSchema(null);
    setRows([]);
    setTotal(0);
    setMessage(null);
    setPending(false);
    setBusy(nextBusy);
    setPage(1);
  };

  const applyKind = (next: ViewAs) => {
    const listSeq = ++groupsSeq.current;
    const ready = next === "none" || next === "user" || (next === "role" && Boolean(roleId));
    clearResults(ready);
    setKind(next);
    setGroupId(null);
    setGroups([]);
    setGroupsLoad(next === "group" ? "loading" : null);
    if (next !== "group") return;
    void listAccountGroups()
      .then((listed) => {
        if (listSeq !== groupsSeq.current) return;
        setGroups(listed.groups.map((group) => ({ id: group.id, name: group.name })));
        setGroupsLoad("ready");
      })
      .catch((err: unknown) => {
        if (listSeq !== groupsSeq.current) return;
        setGroupsLoad(null);
        setMessage(explain(err));
      });
  };

  const applyGroup = (id: string | null) => {
    clearResults(Boolean(id));
    setGroupId(id);
  };

  useEffect(() => {
    if (!active || !selectionReady) return;
    const seq = ++requestSeq.current;
    setBusy(true);
    setPending(false);
    setMessage(null);
    const schemaBody = narrowBody(kind, narrowKey);
    const queryBody = {
      limit: PAGE_SIZE,
      offset: pageToOffset(page, PAGE_SIZE),
      ...schemaBody,
    };
    void (async () => {
      try {
        const next = await loadDataSchema(tableName, schemaBody);
        if (seq !== requestSeq.current) return;
        const result = await queryDataRows(tableName, queryBody);
        if (seq !== requestSeq.current) return;
        setSchema(next);
        setRows(result.items);
        setTotal(result.total);
      } catch (err) {
        if (seq !== requestSeq.current) return;
        setSchema(null);
        setRows([]);
        setTotal(0);
        setPending(err instanceof ApiError && classifyAccessProblem(err.code) === "pending");
        setMessage(explain(err));
      } finally {
        if (seq === requestSeq.current) setBusy(false);
      }
    })();
    return () => {
      if (requestSeq.current === seq) requestSeq.current += 1;
    };
  }, [active, selectionReady, kind, narrowKey, tableName, page, reloadNonce]);

  return (
    <Stack>
      {physicalHidden ? <Alert>{t("entities.data.physicalHidden")}</Alert> : null}
      <Group align="end">
        <Select
          label={t("entities.data.narrow")}
          description={kind === "none" ? undefined : t("entities.data.narrowHint")}
          data={[
            { value: "none", label: t("entities.data.narrow.none") },
            { value: "user", label: t("entities.data.narrow.user") },
            ...(roleId
              ? [
                  {
                    value: "role",
                    label: t("entities.data.narrow.role", {
                      name: me?.role_name || roleId,
                    }),
                  },
                ]
              : []),
            { value: "group", label: t("entities.data.narrow.group") },
          ]}
          value={kind}
          onChange={(value) => applyKind((value as ViewAs) ?? "none")}
        />
        {groupsLoad === "loading" ? (
          <Select
            label={t("entities.data.group")}
            data={[]}
            value={null}
            disabled
            rightSection={<Loader size="xs" />}
          />
        ) : null}
        {groupsLoad === "ready" && groups.length > 0 ? (
          <Select
            label={t("entities.data.group")}
            data={groups.map((group) => ({ value: group.id, label: group.name }))}
            value={groupId}
            onChange={applyGroup}
          />
        ) : null}
        {groupsLoad === "ready" && groups.length === 0 ? (
          <Text size="sm">{t("entities.data.noGroups")}</Text>
        ) : null}
        <Button
          variant="default"
          size="sm"
          loading={busy}
          disabled={!selectionReady}
          onClick={() => setReloadNonce((current) => current + 1)}
        >
          {pending ? t("entities.data.retry") : t("entities.data.refresh")}
        </Button>
      </Group>
      {message ? <Alert color={pending ? "yellow" : "red"}>{message}</Alert> : null}
      {busy && !schema ? <SkeletonRows /> : null}
      {schema ? (
        <Stack gap="sm">
          <Table.ScrollContainer minWidth={480}>
            <Table>
              <Table.Thead>
                <Table.Tr>
                  {schema.attributes.map((attribute) => {
                    const masked = isMaskedPresentation(attribute.presentation?.levels);
                    const varying = Boolean(attribute.presentation?.row_varying);
                    return (
                      <Table.Th key={attribute.name}>
                        {attribute.name}
                        {masked ? ` · ${t("entities.access.cell.masked")}` : ""}
                        {varying ? ` · ${t("entities.access.cell.rowVarying")}` : ""}
                        {attribute.writable === false ? ` · ${t("entities.data.readOnly")}` : ""}
                      </Table.Th>
                    );
                  })}
                </Table.Tr>
              </Table.Thead>
              <Table.Tbody
                aria-busy={busy || undefined}
                style={busy ? { opacity: 0.6 } : undefined}
              >
                {rows.map((row, index) => {
                  const held = withheldNames(row, schema.withheld_field);
                  return (
                    <Table.Tr key={String(row.row_id ?? index)}>
                      {schema.attributes.map((attribute) => {
                        const cell = presentCell({
                          name: attribute.name,
                          value: row[attribute.name],
                          withheld: held,
                          referenceHidden:
                            attribute.type === "reference" && attribute.target == null,
                        });
                        const text =
                          cell.kind === "withheld"
                            ? t("entities.access.cell.withheld")
                            : cell.kind === "empty"
                              ? t("entities.access.cell.empty")
                              : cell.kind === "inaccessible_record"
                                ? t("entities.access.cell.inaccessibleRecord")
                                : cell.text;
                        return <Table.Td key={attribute.name}>{text}</Table.Td>;
                      })}
                    </Table.Tr>
                  );
                })}
              </Table.Tbody>
            </Table>
          </Table.ScrollContainer>
          {rows.length === 0 ? (
            <Stack gap="xs">
              <EmptyState
                message={
                  kind === "none" ? t("entities.data.empty") : t("entities.data.emptyNarrowed")
                }
              />
              {kind === "none" ? null : (
                <Button variant="subtle" size="sm" w="fit-content" onClick={() => applyKind("none")}>
                  {t("entities.data.useFullAccess")}
                </Button>
              )}
            </Stack>
          ) : null}
          {total > 0 ? (
            <ListPager
              page={page}
              pageSize={PAGE_SIZE}
              total={total}
              onChange={setPage}
              disabled={busy}
            />
          ) : null}
        </Stack>
      ) : null}
    </Stack>
  );
}
