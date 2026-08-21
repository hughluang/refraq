"use client";

import { Button } from "@mantine/core";
import { CanAccess } from "@refinedev/core";
import Link from "next/link";
import type { ReactNode } from "react";

type CreateListActionProps = {
  resource: string;
  action?: string;
  children: ReactNode;
  href?: string;
  onClick?: () => void;
};

export function CreateListAction({
  resource,
  action = "create",
  children,
  href,
  onClick,
}: CreateListActionProps) {
  const button = href ? (
    <Button component={Link} href={href} size="sm">
      {children}
    </Button>
  ) : (
    <Button size="sm" onClick={onClick}>
      {children}
    </Button>
  );
  return (
    <CanAccess resource={resource} action={action}>
      {button}
    </CanAccess>
  );
}
