"use client";

import { Button, Stack, Table, Text } from "@mantine/core";
import { useTranslate } from "@refinedev/core";

import { ListTable } from "@/components/display/ListTable";
import type { PendingFederatedIdentity } from "@/features/identity-providers/types";
import { useFormatInstant } from "@/hooks/useFormatInstant";
import { listPresentationOf } from "@/lib/list-state";

type PendingFederatedIdentityTableProps = {
  items: PendingFederatedIdentity[];
  total: number;
  page: number;
  pageSize: number;
  loading: boolean;
  error: string | null;
  errorRequestId: string | null;
  onPageChange: (page: number) => void;
  onRetry: () => void;
  onClaim: (item: PendingFederatedIdentity) => void;
};

export function PendingFederatedIdentityTable({
  items,
  total,
  page,
  pageSize,
  loading,
  error,
  errorRequestId,
  onPageChange,
  onRetry,
  onClaim,
}: PendingFederatedIdentityTableProps) {
  const t = useTranslate();
  const formatInstant = useFormatInstant();
  const presentation = listPresentationOf({
    loading,
    error,
    total,
    itemCount: items.length,
    filtered: false,
  });

  return (
    <ListTable
      state={presentation.state}
      columnCount={7}
      refreshing={presentation.refreshing}
      errorMessage={error}
      errorRequestId={errorRequestId}
      onRetry={onRetry}
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
      page={page}
      pageSize={pageSize}
      total={total}
      onPageChange={onPageChange}
    >
      {items.map((item) => (
        <Table.Tr key={item.id}>
          <Table.Td>
            <Stack gap={2}>
              <Text size="sm" fw={500}>
                {item.display_name ?? item.account_hint}
              </Text>
              <Text size="xs" c="dimmed">
                {item.account_hint}
                {item.email ? ` · ${item.email}` : ""}
              </Text>
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
          <Table.Td>{formatInstant(item.expires_at)}</Table.Td>
          <Table.Td>{item.attempt_count}</Table.Td>
          <Table.Td>
            <Button size="xs" onClick={() => onClaim(item)}>
              {t("users.pending.claim")}
            </Button>
          </Table.Td>
        </Table.Tr>
      ))}
    </ListTable>
  );
}
