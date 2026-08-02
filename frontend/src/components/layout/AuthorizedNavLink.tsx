"use client";

import { NavLink } from "@mantine/core";
import { CanAccess, useTranslate, type TreeMenuItem } from "@refinedev/core";
import Link from "next/link";

type AuthorizedNavLinkProps = {
  item: TreeMenuItem;
  pathname: string;
  onNavigate?: () => void;
};

export function AuthorizedNavLink({
  item,
  pathname,
  onNavigate,
}: AuthorizedNavLinkProps) {
  const t = useTranslate();
  const href = item.route;
  if (!href) return null;

  const labelKey = typeof item.label === "string" ? item.label : item.name;
  const active =
    pathname === href ||
    (href !== "/console" && pathname.startsWith(`${href}/`));

  return (
    <CanAccess
      resource={item.name}
      action="list"
      params={{ resource: item }}
    >
      <NavLink
        component={Link}
        href={href}
        label={t(labelKey)}
        active={active}
        onClick={onNavigate}
      />
    </CanAccess>
  );
}
