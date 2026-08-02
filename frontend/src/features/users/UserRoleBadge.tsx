"use client";

import { Badge } from "@mantine/core";
import { useTranslate } from "@refinedev/core";

type UserRoleBadgeProps = {
  roleName: string | null;
  roleKey: string | null;
};

export function UserRoleBadge({ roleName, roleKey }: UserRoleBadgeProps) {
  const t = useTranslate();
  if (!roleKey) {
    return (
      <Badge color="gray" variant="light">
        {t("users.roles.none")}
      </Badge>
    );
  }
  return (
    <Badge color={roleKey === "super_admin" ? "red" : "blue"} variant="light">
      {roleName ?? roleKey}
    </Badge>
  );
}
