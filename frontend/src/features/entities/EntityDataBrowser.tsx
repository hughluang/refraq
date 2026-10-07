"use client";

import {
  Alert,
  Button,
  Group,
  Select,
  Stack,
  Table,
  Text,
  Title,
} from "@mantine/core";
import { useTranslate } from "@refinedev/core";
import { useState } from "react";

import { loadDataSchema, queryDataRows } from "@/features/entities/accessApi";
import {
  classifyAccessProblem,
  isMaskedPresentation,
  narrowBody,
  presentCell,
  withheldNames,
} from "@/features/entities/accessLogic";
import type { DataSchema } from "@/features/entities/accessTypes";
import { listRoles } from "@/features/roles/api";
import { listUserGroups } from "@/features/subjects/api";
import { ApiError } from "@/lib/api";

type Props = {
  tableName: string;
  physicalHidden: boolean;
};

export function EntityDataBrowser({ tableName, physicalHidden }: Props) {
  const t = useTranslate();
  const [kind, setKind] = useState<"none" | "user" | "role" | "group">("none");
  const [identity, setIdentity] = useState<string | null>(null);
  const [options, setOptions] = useState<{ value: string; label: string }[]>([]);
  const [schema, setSchema] = useState<DataSchema | null>(null);
  const [rows, setRows] = useState<Record<string, unknown>[]>([]);
  const [message, setMessage] = useState<string | null>(null);
  const [pending, setPending] = useState(false);
  const [busy, setBusy] = useState(false);

  const explain = (err: unknown) => {
    if (!(err instanceof ApiError)) return String(err);
    const problem = classifyAccessProblem(err.code);
    if (problem === "pending") return t("entities.data.pending");
    if (problem === "write_denied") return t("entities.data.writeDenied");
    if (problem === "conflict") return t("entities.data.conflict");
    if (problem === "combination_limit") return t("entities.access.overLimit");
    return err.detail;
  };

  const load = async () => {
    setBusy(true);
    setPending(false);
    setMessage(null);
    const body = { limit: 50, offset: 0, ...narrowBody(kind, identity ?? "") };
    try {
      const next = await loadDataSchema(tableName, body);
      setSchema(next);
      const page = await queryDataRows(tableName, body);
      setRows(page.items);
    } catch (err) {
      setSchema(null);
      setRows([]);
      setPending(err instanceof ApiError && classifyAccessProblem(err.code) === "pending");
      setMessage(explain(err));
    } finally {
      setBusy(false);
    }
  };

  return (
    <Stack>
      <Title order={4}>{t("entities.tabs.data")}</Title>
      {physicalHidden ? <Alert>{t("entities.data.physicalHidden")}</Alert> : null}
      <Text size="sm">{t("entities.data.narrowHint")}</Text>
      <Group align="end">
        <Select
          label={t("entities.data.narrow")}
          data={[
            { value: "none", label: t("entities.data.narrow.none") },
            { value: "user", label: t("entities.data.narrow.user") },
            { value: "role", label: t("entities.data.narrow.role") },
            { value: "group", label: t("entities.data.narrow.group") },
          ]}
          value={kind}
          onChange={(value) => {
            const next = (value as typeof kind) ?? "none";
            setKind(next);
            setIdentity(null);
            if (next === "role") {
              void listRoles({ limit: 100, offset: 0 }).then((page) =>
                setOptions(page.items.map((row) => ({ value: row.id, label: row.name }))),
              );
            }
            if (next === "group") {
              void listUserGroups({ limit: 100, offset: 0 }).then((page) =>
                setOptions(page.items.map((row) => ({ value: row.id, label: row.name }))),
              );
            }
          }}
        />
        {kind === "role" || kind === "group" ? (
          <Select
            label={t("entities.access.grants.subject")}
            data={options}
            value={identity}
            onChange={setIdentity}
          />
        ) : null}
        <Button loading={busy} onClick={() => void load()}>
          {t("entities.data.load")}
        </Button>
        {pending ? (
          <Button variant="light" loading={busy} onClick={() => void load()}>
            {t("entities.data.retry")}
          </Button>
        ) : null}
      </Group>
      {message ? <Alert color={pending ? "yellow" : "red"}>{message}</Alert> : null}
      {schema ? (
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
            <Table.Tbody>
              {rows.length === 0 ? (
                <Table.Tr>
                  <Table.Td colSpan={Math.max(schema.attributes.length, 1)}>
                    {t("entities.data.empty")}
                  </Table.Td>
                </Table.Tr>
              ) : (
                rows.map((row, index) => {
                  const held = withheldNames(row, schema.withheld_field);
                  return (
                    <Table.Tr key={String(row.row_id ?? index)}>
                      {schema.attributes.map((attribute) => {
                        const cell = presentCell({
                          name: attribute.name,
                          value: row[attribute.name],
                          withheld: held,
                          masked: isMaskedPresentation(attribute.presentation?.levels),
                          rowVarying: Boolean(attribute.presentation?.row_varying),
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
              )}
            </Table.Tbody>
          </Table>
        </Table.ScrollContainer>
      ) : null}
    </Stack>
  );
}
