"use client";

import { Table } from "@mantine/core";
import { useTranslate } from "@refinedev/core";

export function ScheduleTableHead() {
  const t = useTranslate();

  return (
    <Table.Tr>
      <Table.Th>{t("schedules.fields.kind")}</Table.Th>
      <Table.Th>{t("schedules.fields.cadence")}</Table.Th>
      <Table.Th>{t("schedules.fields.enabled")}</Table.Th>
      <Table.Th>{t("schedules.fields.nextRun")}</Table.Th>
      <Table.Th>{t("schedules.fields.recentRuns")}</Table.Th>
      <Table.Th />
    </Table.Tr>
  );
}
