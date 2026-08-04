"use client";

import { NavLink } from "@mantine/core";
import { useTranslate } from "@refinedev/core";
import Link from "next/link";

type ConsoleNavLinkProps = {
  labelKey: string;
  href: string;
  pathname: string;
  onNavigate?: () => void;
};

export function ConsoleNavLink({
  labelKey,
  href,
  pathname,
  onNavigate,
}: ConsoleNavLinkProps) {
  const t = useTranslate();
  const active =
    pathname === href ||
    (href !== "/console" && pathname.startsWith(`${href}/`));

  return (
    <NavLink
      component={Link}
      href={href}
      label={t(labelKey)}
      active={active}
      onClick={onNavigate}
    />
  );
}
