"use client";

import {
  ActionIcon,
  Button,
  Group,
  Loader,
  Select,
  Stack,
  Text,
  Tooltip,
  VisuallyHidden,
} from "@mantine/core";
import { useGetIdentity, useTranslate } from "@refinedev/core";
import { useCallback, useEffect, useMemo, useRef, useState, type ReactNode } from "react";

import { RepeatIcon } from "@/components/icons";
import { FillColumn } from "@/components/layout/FillColumn";
import { Callout } from "@/components/feedback/Callout";
import { ProblemDetails } from "@/components/feedback/ProblemDetails";
import { presentProblemNotification } from "@/components/feedback/presentProblemNotification";
import { listAccountGroups } from "@/features/account/api";
import { loadDataSchema, queryDataRows, type DataQueryBody } from "./accessApi";
import {
  classifyAccessProblem,
  dataAccessExpired,
  narrowBody,
  type DataSchemaBody,
} from "./accessLogic";
import type { DataSchema } from "./accessTypes";
import { EntityDataColumns, EntityDataResults } from "./EntityDataResults";
import { stringifyEntityDataJson } from "./entityDataJson";
import { EntityDataQueryControls } from "./EntityDataQueryControls";
import { compileDataQuery, EMPTY_DATA_QUERY, writeDataQuery } from "./entityDataQuery";
import {
  changeDataPage,
  clearDataOptions,
  readDataLocation,
  updateDataLocation,
  useDataLocation,
} from "./entityDataLocation";
import { ApiError } from "@/lib/api";
import { listPresentationOf } from "@/lib/list-state";
import { pageCountOf, pageToOffset } from "@/lib/pagination";
import { presentConsoleNotification } from "@/providers/notification-provider";
import type { CurrentUser } from "@/providers/session-store";

type Translate = (key: string) => string;
/** Copy that replaces a misleading server detail. Null means use the problem message. */
function replacedTitle(translate: Translate, err: ApiError): string | null {
  if (err.code === "ENTITY_NOT_FOUND") return translate("entities.data.noGrant");
  if (err.code === "ENTITY_ACCESS_INVALID") return translate("entities.data.narrowRejected");
  const problem = classifyAccessProblem(err.code);
  if (problem === "pending") return translate("entities.data.pending");
  if (problem === "combination_limit") return translate("entities.access.overLimit");
  return null;
}

function notifyFailure(translate: Translate, err: unknown, onRetry: () => void) {
  if (!(err instanceof ApiError)) {
    presentProblemNotification(translate, err, { onRetry });
    return;
  }
  const replaced = replacedTitle(translate, err);
  if (replaced == null) {
    presentProblemNotification(translate, err, { onRetry });
    return;
  }
  const requestId = err.requestId?.trim() ? err.requestId : null;
  const retry = (
    <Button type="button" size="compact-xs" variant="subtle" onClick={onRetry}>
      {translate("common.retry")}
    </Button>
  );
  presentConsoleNotification({
    type: "error",
    title: replaced,
    message:
      requestId == null ? (
        retry
      ) : (
        <Stack gap={4}>
          <ProblemDetails
            detail={null}
            requestId={requestId}
            labels={{
              summary: translate("form.error.details"),
              requestId: translate("common.requestId"),
              copy: translate("form.error.copy"),
              copied: translate("common.copy.success"),
              copyFailed: translate("common.copy.failed"),
            }}
          />
          {retry}
        </Stack>
      ),
  });
}

type Props = { tableName: string; physicalHidden: boolean; active: boolean };
type ViewAs = "none" | "user" | "role" | "group";

export function EntityDataBrowser({ tableName, physicalHidden, active }: Props) {
  const { data: me } = useGetIdentity<CurrentUser>();
  const search = useDataLocation();
  if (!active || search === null) return null;
  return (
    <DataView
      key={JSON.stringify([tableName, me?.id, me?.role_id])}
      tableName={tableName}
      physicalHidden={physicalHidden}
      search={search}
      me={me}
    />
  );
}

function DataView({
  tableName,
  physicalHidden,
  search,
  me,
}: {
  tableName: string;
  physicalHidden: boolean;
  search: string;
  me?: CurrentUser;
}) {
  const t = useTranslate();
  const params = new URLSearchParams(search);
  const kind = params.get("dataView") ?? "none";
  const groupId = params.get("dataGroup");
  const roleId = me?.role_id;
  const [groups, setGroups] = useState<{ id: string; name: string }[] | null>(null);
  const [groupsFailed, setGroupsFailed] = useState(false);
  const [groupRetry, setGroupRetry] = useState(0);
  const tRef = useRef(t);
  tRef.current = t;

  useEffect(() => {
    setGroupsFailed(false);
    if (kind !== "group") {
      setGroups(null);
      return;
    }
    let current = true;
    setGroups(null);
    void listAccountGroups()
      .then((response) => {
        if (current) setGroups(response.groups);
      })
      .catch((err: unknown) => {
        if (current) {
          setGroupsFailed(true);
          notifyFailure(tRef.current, err, () => setGroupRetry((n) => n + 1));
        }
      });
    return () => {
      current = false;
    };
  }, [kind, groupRetry]);

  const selectIdentity = (value: string, group?: string | null) =>
    updateDataLocation((next) => {
      clearDataOptions(next);
      next.delete("dataGroup");
      if (value === "none") next.delete("dataView");
      else next.set("dataView", value);
      if (group) next.set("dataGroup", group);
    });
  const validKind = kind === "none" || kind === "user" || kind === "role" || kind === "group";
  const invalidIdentity =
    !validKind ||
    params.getAll("dataView").length > 1 ||
    params.getAll("dataGroup").length > 1 ||
    (kind !== "group" && groupId !== null) ||
    (kind === "role" && !roleId) ||
    (kind === "group" &&
      groupId !== null &&
      groups !== null &&
      !groups.some((g) => g.id === groupId));
  const ready = !invalidIdentity && (kind !== "group" || Boolean(groupId && groups));
  const scopeId = (kind === "group" ? groupId : kind === "role" ? roleId : "") ?? "";
  const narrow = useMemo(() => narrowBody(kind as ViewAs, scopeId), [kind, scopeId]);

  const identity = (
    <>
      <Tooltip label={t("entities.data.narrow")} withArrow>
        <Select
          aria-label={t("entities.data.narrow")}
          size="sm"
          w={154}
          allowDeselect={false}
          description={
            kind === "none" ? undefined : (
              <VisuallyHidden>{t("entities.data.narrowHint")}</VisuallyHidden>
            )
          }
          data={[
            { value: "none", label: t("entities.data.narrow.none") },
            { value: "user", label: t("entities.data.narrow.user") },
            ...(roleId
              ? [
                  {
                    value: "role",
                    label: t("entities.data.narrow.role", { name: me?.role_name || roleId }),
                  },
                ]
              : []),
            { value: "group", label: t("entities.data.narrow.group") },
          ]}
          value={validKind ? kind : null}
          onChange={(v) => v && selectIdentity(v)}
        />
      </Tooltip>
      {kind === "group" && !groupsFailed && (groups === null || groups.length > 0) && (
        <Select
          aria-label={t("entities.data.group")}
          placeholder={t("entities.data.group")}
          w={150}
          searchable
          disabled={groups === null}
          value={groupId}
          data={(groups ?? []).map(({ id, name }) => ({ value: id, label: name }))}
          rightSection={groups === null ? <Loader size="xs" /> : undefined}
          onChange={(id) => selectIdentity("group", id)}
        />
      )}
    </>
  );

  return (
    <FillColumn gap="xs">
      {physicalHidden && <Callout tone="info">{t("entities.data.physicalHidden")}</Callout>}
      <ScopedData
        key={JSON.stringify([kind, scopeId])}
        tableName={tableName}
        identity={identity}
        search={search}
        narrow={narrow}
        ready={ready}
        onFullAccess={() => selectIdentity("none")}
      />
      {kind === "group" && groups?.length === 0 && (
        <Text size="sm">{t("entities.data.noGroups")}</Text>
      )}
      {invalidIdentity && <Callout tone="notice">{t("entities.data.narrowRejected")}</Callout>}
    </FillColumn>
  );
}

function pageRequest(
  schema: DataSchema,
  options: ReturnType<typeof readDataLocation>,
  fields: string[] | null,
) {
  const { query, size, page, sort } = options;
  if (
    !options.valid ||
    !query ||
    size > (schema.limits?.page_limit_max ?? 50) ||
    (sort &&
      sort.field !== "row_id" &&
      !schema.attributes.some((a) => a.name === sort.field && a.type !== "json"))
  ) {
    return { error: "entities.data.invalidOptions" } as const;
  }
  const compiled = compileDataQuery(query, schema);
  if (!compiled.ok) return { error: compiled.error } as const;
  const body: DataQueryBody = { limit: size, offset: pageToOffset(page, size) };
  if (compiled.filters) body.filters = compiled.filters;
  if (sort) body.sort = sort;
  if (fields !== null) {
    body.fields = [
      "row_id",
      ...schema.attributes.map((a) => a.name).filter((name) => fields.includes(name)),
    ];
  }
  return { body } as const;
}

function ScopedData({
  tableName,
  identity,
  search,
  narrow,
  ready,
  onFullAccess,
}: {
  tableName: string;
  identity: ReactNode;
  search: string;
  narrow: DataSchemaBody;
  ready: boolean;
  onFullAccess: () => void;
}) {
  const t = useTranslate();
  const tRef = useRef(t);
  tRef.current = t;
  const options = useMemo(() => readDataLocation(search), [search]);
  const [fields, setFields] = useState<string[] | null>(null);
  const [reload, setReload] = useState(0);
  const [rejected, setRejected] = useState<string | null>(null);
  const refresh = useCallback(() => {
    setRejected(null);
    setReload((n) => n + 1);
  }, []);
  const [loaded, setLoaded] = useState<{ schema: DataSchema; reload: number } | null>(null);
  const [result, setResult] = useState<{
    items: Record<string, unknown>[];
    total: number;
    request: string;
  } | null>(null);
  const [busy, setBusy] = useState(ready);
  const [failure, setFailure] = useState(false);
  const [pending, setPending] = useState(false);
  const schema = loaded?.schema ?? null;
  const request = useMemo(
    () => (schema ? pageRequest(schema, options, fields) : null),
    [schema, options, fields],
  );
  const body = request?.body;
  const requestKey = stringifyEntityDataJson([
    body,
    schema?.head?.version_id,
    schema?.access?.policy_revision,
  ]);
  const rejectedRequest = rejected === requestKey;
  useEffect(() => setRejected(null), [search, fields]);
  const rows = result?.request === requestKey ? result.items : [];
  const total = result?.request === requestKey ? result.total : 0;

  const fail = useCallback(
    (err: unknown) => {
      setBusy(false);
      setFailure(true);
      setPending(err instanceof ApiError && classifyAccessProblem(err.code) === "pending");
      if (dataAccessExpired(err)) {
        setResult(null);
        setLoaded(null);
      }
      notifyFailure(tRef.current, err, refresh);
    },
    [refresh],
  );

  useEffect(() => {
    if (!ready) return;
    let current = true;
    setBusy(true);
    setFailure(false);
    setPending(false);
    void loadDataSchema(tableName, narrow)
      .then((next) => {
        if (current) setLoaded({ schema: next, reload });
      })
      .catch((err: unknown) => {
        if (current) fail(err);
      });
    return () => {
      current = false;
    };
  }, [tableName, narrow, ready, reload, fail]);

  useEffect(() => {
    if (!ready || loaded?.reload !== reload || !body || rejectedRequest) return;
    let current = true;
    setBusy(true);
    setFailure(false);
    void queryDataRows(tableName, { ...body, ...narrow })
      .then((page) => {
        if (!current) return;
        const lastPage = Math.max(1, pageCountOf(page.total, options.size));
        if (options.page > lastPage) {
          changeDataPage(lastPage);
          return;
        }
        setResult({ items: page.items, total: page.total, request: requestKey });
        setBusy(false);
      })
      .catch((err: unknown) => {
        if (!current) return;
        if (
          err instanceof ApiError &&
          (err.code === "ENTITY_ROW_INVALID" || err.code === "REQUEST_INVALID")
        ) {
          // The serving schema or its limits may have changed since the toolbar was loaded.
          setRejected(requestKey);
          setLoaded(null);
          setResult(null);
          setReload((n) => n + 1);
          notifyFailure(tRef.current, err, refresh);
        } else {
          fail(err);
        }
      });
    return () => {
      current = false;
    };
  }, [
    ready,
    tableName,
    loaded,
    reload,
    body,
    narrow,
    options,
    requestKey,
    rejectedRequest,
    refresh,
    fail,
  ]);

  const clearQuery = () =>
    updateDataLocation((params) => {
      writeDataQuery(params, EMPTY_DATA_QUERY);
      params.delete("dataPage");
    });
  const filtered = Boolean(options.query?.lookup || options.query?.conditions.length);
  const invalid = request?.error ?? (rejectedRequest ? "entities.data.invalidOptions" : null);
  const refreshLabel = t(pending ? "entities.data.retry" : "entities.data.refresh");
  const actions = (
    <>
      {identity}
      <Tooltip label={refreshLabel}>
        <ActionIcon
          type="button"
          variant="default"
          size="lg"
          aria-label={refreshLabel}
          loading={busy && !invalid}
          disabled={!ready}
          onClick={refresh}
        >
          <RepeatIcon />
        </ActionIcon>
      </Tooltip>
    </>
  );

  return (
    <>
      {schema ? (
        <EntityDataQueryControls
          schema={schema}
          query={options.query ?? EMPTY_DATA_QUERY}
          onChange={(next) =>
            updateDataLocation((params) => {
              writeDataQuery(params, next);
              params.delete("dataPage");
            })
          }
          columnAction={
            <EntityDataColumns schema={schema} visibleFields={fields} onChange={setFields} />
          }
          actions={actions}
        />
      ) : (
        <Group gap="xs" justify="flex-end">
          {actions}
        </Group>
      )}
      {invalid ? (
        <Callout tone="notice">
          <Group gap="xs">
            <Text size="sm">{t(invalid)}</Text>
            <Button
              type="button"
              variant="subtle"
              size="compact-sm"
              onClick={() => updateDataLocation(clearDataOptions)}
            >
              {t("entities.data.resetQuery")}
            </Button>
          </Group>
        </Callout>
      ) : (
        ready && (
          <EntityDataResults
            key={JSON.stringify([
              schema?.head?.version_id,
              schema?.access?.policy_revision,
              reload,
            ])}
            schema={schema}
            rows={rows}
            tableName={tableName}
            narrow={narrow}
            visibleFields={fields}
            sort={options.sort}
            onDetailError={fail}
            onSort={(sort) =>
              updateDataLocation((params) => {
                params.delete("dataPage");
                if (sort) {
                  params.set("dataSort", sort.field);
                  params.set("dataDirection", sort.direction);
                } else {
                  params.delete("dataSort");
                  params.delete("dataDirection");
                }
              })
            }
            onPageSize={(size) =>
              updateDataLocation((params) => {
                params.delete("dataPage");
                if (size === 50) params.delete("dataSize");
                else params.set("dataSize", String(size));
              })
            }
            list={{
              presentation: listPresentationOf({
                loading: busy,
                error: failure ? "failed" : null,
                total,
                itemCount: rows.length,
                filtered: filtered || Boolean(narrow.narrow),
              }),
              page: options.page,
              setPage: changeDataPage,
              pageSize: options.size,
              total,
              reload: refresh,
            }}
            noMatchMessage={t(filtered ? "entities.data.noMatches" : "entities.data.emptyNarrowed")}
            noMatchAction={
              <Button
                type="button"
                variant="subtle"
                size="xs"
                onClick={filtered ? clearQuery : onFullAccess}
              >
                {t(filtered ? "common.filters.clear" : "entities.data.useFullAccess")}
              </Button>
            }
          />
        )
      )}
    </>
  );
}
