"use client";

import { Alert, Button, Checkbox, Collapse, Group, Select, Stack, Table, Text } from "@mantine/core";
import { useTranslate } from "@refinedev/core";
import { useState } from "react";

import { previewAccess } from "@/features/entities/accessApi";
import { presentCell, withheldNames } from "@/features/entities/accessLogic";
import { accessProblemText } from "@/features/entities/accessProblem";
import type { AccessOption, AccessRun } from "@/features/entities/accessSession";
import { SectionHeader } from "@/components/layout/SectionHeader";

type PreviewColumn = { name: string; marks: string };
type PreviewModel = { columns: PreviewColumn[]; headers: string[]; rows: string[][] };

type Props = {
  entityId: string;
  users: AccessOption[];
  canPreviewRows: boolean;
  busyId: string | null;
  run: AccessRun;
};

export function AccessPreviewSection({
  entityId,
  users,
  canPreviewRows,
  busyId,
  run,
}: Props) {
  const t = useTranslate();
  const [open, setOpen] = useState(false);
  const [previewUser, setPreviewUser] = useState<string | null>(null);
  const [includeRows, setIncludeRows] = useState(false);
  const [preview, setPreview] = useState<PreviewModel | null>(null);
  const [error, setError] = useState<string | null>(null);
  const running = busyId === "preview";

  return (
    <Stack gap="sm">
      <SectionHeader
        order={4}
        title={t("entities.access.preview")}
        description={t("entities.access.preview.description")}
        actions={
          <Button size="sm" variant="default" onClick={() => setOpen((current) => !current)}>
            {open ? t("entities.access.collapse") : t("entities.access.expand")}
          </Button>
        }
      />
      <Collapse expanded={open}>
        <Stack gap="sm">
          <Group align="flex-end">
            <Select
              label={t("entities.access.subject.user")}
              data={users}
              value={previewUser}
              onChange={setPreviewUser}
              searchable
            />
            <Checkbox
              label={t("entities.access.preview.includeRows")}
              checked={includeRows && canPreviewRows}
              disabled={!canPreviewRows}
              onChange={(event) => setIncludeRows(event.currentTarget.checked)}
            />
            <Button
              loading={running}
              disabled={!previewUser || (busyId !== null && !running)}
              onClick={() =>
                void run("preview", null, async () => {
                  try {
                    const result = await previewAccess(entityId, {
                      subject: { type: "user", id: previewUser as string },
                      include_rows: includeRows && canPreviewRows,
                    });
                    const columns = result.schema.attributes.map((attribute) => {
                      const marks = [
                        attribute.presentation?.row_varying
                          ? t("entities.access.cell.rowVarying")
                          : "",
                        attribute.presentation?.may_be_withheld
                          ? t("entities.access.cell.withheld")
                          : "",
                      ].filter(Boolean);
                      return {
                        name: attribute.name,
                        marks: marks.join(t("entities.access.summary.actionJoin")),
                      };
                    });
                    const headers = result.schema.attributes.map((attribute) => attribute.name);
                    const rows = (result.rows?.items ?? []).map((row) => {
                      const held = withheldNames(row, result.schema.withheld_field);
                      const sources = row.__sources;
                      return result.schema.attributes.map((attribute) => {
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
                      });
                    });
                    setPreview({ columns, headers, rows });
                    setError(null);
                  } catch (err) {
                    setPreview(null);
                    setError(accessProblemText(err, t));
                  }
                })
              }
            >
              {t("entities.access.preview.run")}
            </Button>
          </Group>
          {canPreviewRows ? null : (
            <Text size="sm" c="dimmed">
              {t("entities.access.preview.rowsDenied")}
            </Text>
          )}
          {error ? <Alert color="red">{error}</Alert> : null}
          {preview ? (
            <Stack gap="sm">
              <Text fw={600}>{t("entities.access.preview.columns")}</Text>
              <Table.ScrollContainer minWidth={480}>
                <Table>
                  <Table.Thead>
                    <Table.Tr>
                      <Table.Th>{t("entities.access.profiles.column")}</Table.Th>
                      <Table.Th>{t("entities.access.preview.marks")}</Table.Th>
                    </Table.Tr>
                  </Table.Thead>
                  <Table.Tbody>
                    {preview.columns.map((column) => (
                      <Table.Tr key={column.name}>
                        <Table.Td>{column.name}</Table.Td>
                        <Table.Td>
                          {column.marks || t("entities.access.preview.noMarks")}
                        </Table.Td>
                      </Table.Tr>
                    ))}
                  </Table.Tbody>
                </Table>
              </Table.ScrollContainer>
              {preview.rows.length > 0 ? (
                <>
                  <Text fw={600}>{t("entities.access.preview.rows")}</Text>
                  <Table.ScrollContainer minWidth={640}>
                    <Table>
                      <Table.Thead>
                        <Table.Tr>
                          {preview.headers.map((header) => (
                            <Table.Th key={header}>{header}</Table.Th>
                          ))}
                        </Table.Tr>
                      </Table.Thead>
                      <Table.Tbody>
                        {preview.rows.map((row, index) => (
                          <Table.Tr key={index}>
                            {row.map((cell, cellIndex) => (
                              <Table.Td key={`${index}-${cellIndex}`}>{cell}</Table.Td>
                            ))}
                          </Table.Tr>
                        ))}
                      </Table.Tbody>
                    </Table>
                  </Table.ScrollContainer>
                </>
              ) : null}
            </Stack>
          ) : null}
        </Stack>
      </Collapse>
    </Stack>
  );
}
