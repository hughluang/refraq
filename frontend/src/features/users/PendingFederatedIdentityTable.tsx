"use client";

import { Stack, Table, Text } from "@mantine/core";
import { useTranslate } from "@refinedev/core";

import { ListTable } from "@/components/display/ListTable";
import { RecordReference } from "@/components/display/RecordReference";
import { RowActions } from "@/components/display/RowActions";
import type { PendingFederatedIdentity } from "@/features/identity-providers/types";
import type { UsePagedListResult } from "@/hooks/usePagedList";
import { useShowInstant } from "@/hooks/useFormatInstant";

type PendingFederatedIdentityTableProps = {
  list: UsePagedListResult<PendingFederatedIdentity>;
  onClaim: (item: PendingFederatedIdentity) => void;
};

export function PendingFederatedIdentityTable({
  list,
  onClaim,
}: PendingFederatedIdentityTableProps) {
  const t = useTranslate();
  const showInstant = useShowInstant();

  return (
    <ListTable
      list={list}
      columnCount={7}
      emptyMessage={t("users.pending.empty")}
      head={
        <Table.Tr>
          <Table.Th>{t("users.fields.displayName")}</Table.Th>
          <Table.Th>{t("identityProviders.fields.issuer")}</Table.Th>
          <Table.Th>{t("users.pending.reason")}</Table.Th>
          <Table.Th>{t("users.pending.groups")}</Table.Th>
          <Table.Th>{t("users.pending.expires")}</Table.Th>
          <Table.Th>{t("users.pending.attempts")}</Table.Th>
          <Table.Th>{t("users.fields.actions")}</Table.Th>
        </Table.Tr>
      }
    >
      {list.items.map((item) => (
        <Table.Tr key={item.id}>
          <Table.Td>
            <Stack gap={2}>
              <RecordReference
                name={item.display_name ?? item.account_hint}
                recordKey={item.account_hint}
              />
              {item.email ? (
                <Text size="xs" c="dimmed">
                  {item.email}
                </Text>
              ) : null}
            </Stack>
          </Table.Td>
          <Table.Td>
            <Text size="sm">{item.issuer}</Text>
          </Table.Td>
          <Table.Td>
            {t(`users.pending.reason.${item.admission_reason}`, {
              defaultValue: item.admission_reason,
            })}
          </Table.Td>
          <Table.Td>
            {item.groups.length
              ? item.groups.join(", ")
              : t("identityProviders.fields.notConfigured")}
          </Table.Td>
          <Table.Td>{showInstant(item.expires_at)}</Table.Td>
          <Table.Td>{item.attempt_count}</Table.Td>
          <Table.Td>
            <RowActions
              recordName={item.display_name ?? item.account_hint}
              verbs={[
                {
                  key: "claim",
                  label: t("users.pending.claim"),
                  safety: "immediate",
                  onClick: () => onClaim(item),
                },
              ]}
            />
          </Table.Td>
        </Table.Tr>
      ))}
    </ListTable>
  );
}
