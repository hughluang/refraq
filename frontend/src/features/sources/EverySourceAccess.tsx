"use client";

import { Modal } from "@mantine/core";
import { useTranslate } from "@refinedev/core";
import { useMemo } from "react";

import {
  changeEverySourceMembership,
  createEverySourceMembership,
  deleteEverySourceMembership,
  listEverySourceMemberships,
} from "@/features/sources/api/memberships";
import { MembershipCollection } from "@/features/sources/MembershipCollection";

type Props = {
  opened: boolean;
  onClose: () => void;
};

export function EverySourceAccess({ opened, onClose }: Props) {
  const t = useTranslate();
  const client = useMemo(
    () => ({
      list: listEverySourceMemberships,
      create: createEverySourceMembership,
      change: changeEverySourceMembership,
      remove: deleteEverySourceMembership,
    }),
    [],
  );
  return (
    <Modal
      opened={opened}
      onClose={onClose}
      title={t("sources.membership.every")}
      size="lg"
    >
      {opened ? <MembershipCollection client={client} editable /> : null}
    </Modal>
  );
}
