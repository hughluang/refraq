"use client";

import {
  Alert,
  Button,
  Group,
  Loader,
  Select,
  Stack,
  Table,
  Text,
} from "@mantine/core";
import { useGetIdentity, useTranslate } from "@refinedev/core";
import { useEffect, useRef, useState } from "react";

import { ListTable } from "@/components/display/ListTable";
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
import { listPresentationOf } from "@/lib/list-state";
import { pageToOffset } from "@/lib/pagination";
import { problemMessage } from "@/lib/problem";
import type { CurrentUser } from "@/providers/session-store";

const PAGE_SIZE = 50;

type Props = {
  tableName: string;
  physicalHidden: boolean;
  active: boolean;
};

type ViewAs = "none" | "user" | "role" | "group";
/** null: not listing groups (or list failed; failure text is in `message`). */
type GroupsLoad = "loading" | "ready" | null;

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
  const [busy, setBusy] = useState(active);
  const [reloadNonce, setReloadNonce] = useState(0);
  const requestSeq = useRef(0);
  const groupsSeq = useRef(0);
  const held = useRef(false);
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
    held.current = false;
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
        held.current = true;
        setSchema(next);
        setRows(result.items);
        setTotal(result.total);
        setMessage(null);
      } catch (err) {
        if (seq !== requestSeq.current) return;
        if (!held.current) {
          setSchema(null);
          setRows([]);
          setTotal(0);
        }
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

  const showError = Boolean(message) && rows.length === 0 && !busy;
  const columnCount = Math.max(schema?.attributes.length ?? 1, 1);
  const list = {
    presentation: listPresentationOf({
      loading: busy,
      error: showError ? message : null,
      total,
      itemCount: rows.length,
      filtered: kind !== "none",
    }),
    error: showError ? message : null,
    errorRequestId: null,
    reload: () => setReloadNonce((current) => current + 1),
    page,
    setPage,
    pageSize: PAGE_SIZE,
    total,
  };
  const showTable = active && (selectionReady || schema != null || message != null || busy);

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
      {message && rows.length > 0 ? (
        <Alert color={pending ? "yellow" : "red"}>{message}</Alert>
      ) : null}
      {showTable ? (
        <ListTable
          embedded
          list={list}
          columnCount={columnCount}
          minWidth={Math.max(480, columnCount * 140)}
          emptyMessage={t("entities.data.empty")}
          noMatchMessage={t("entities.data.emptyNarrowed")}
          noMatchAction={
            kind === "none" ? undefined : (
              <Button variant="subtle" size="xs" onClick={() => applyKind("none")}>
                {t("entities.data.useFullAccess")}
              </Button>
            )
          }
          head={
            <Table.Tr>
              {(schema?.attributes ?? []).map((attribute) => {
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
              {schema ? null : <Table.Th />}
            </Table.Tr>
          }
        >
          {schema
            ? rows.map((row, index) => {
                const withheld = withheldNames(row, schema.withheld_field);
                return (
                  <Table.Tr key={String(row.row_id ?? index)}>
                    {schema.attributes.map((attribute) => {
                      const cell = presentCell({
                        name: attribute.name,
                        value: row[attribute.name],
                        withheld,
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
              })
            : null}
        </ListTable>
      ) : null}
    </Stack>
  );
}
