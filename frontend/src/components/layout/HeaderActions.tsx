"use client";

import { Divider, Group } from "@mantine/core";
import { Children, cloneElement, isValidElement, type ReactElement, type ReactNode } from "react";

/** Clusters for the page-header action row. */
export type HeaderActionsProps = {
  navigation?: ReactNode;
  lifecycle?: ReactNode;
  standard?: ReactNode;
};

type ButtonLikeProps = {
  variant?: string;
  size?: string;
};

export type HeaderActionProps = {
  /** The single filled primary in the header. At most one action may set this. */
  primary?: boolean;
  children: ReactElement<ButtonLikeProps>;
};

export function HeaderAction({ primary = false, children }: HeaderActionProps) {
  return cloneElement(children, {
    size: "sm",
    variant: primary ? "filled" : (children.props.variant ?? "default"),
  });
}

export function assertSinglePrimary(nodes: ReactNode): void {
  let count = 0;
  const visit = (node: ReactNode) => {
    if (!isValidElement(node)) return;
    if (node.type === HeaderAction) {
      if ((node.props as HeaderActionProps).primary === true) count += 1;
      return;
    }
    Children.forEach((node.props as { children?: ReactNode }).children, visit);
  };
  Children.forEach(nodes, visit);
  if (count > 1) {
    throw new Error("Header actions allow one filled primary.");
  }
}

function isPresent(node: ReactNode): boolean {
  if (node == null || node === false || node === true) return false;
  if (Array.isArray(node)) return node.some(isPresent);
  return true;
}

export function HeaderActions({
  navigation,
  lifecycle,
  standard,
}: HeaderActionsProps) {
  if (process.env.NODE_ENV === "development") {
    assertSinglePrimary([navigation, lifecycle, standard]);
  }
  const clusters = [navigation, lifecycle, standard].filter(isPresent);
  return (
    <Group gap="sm" wrap="wrap" align="center">
      {clusters.map((cluster, index) => (
        <Group key={index} gap="sm" wrap="wrap" align="center">
          {index > 0 ? <Divider orientation="vertical" /> : null}
          {cluster}
        </Group>
      ))}
    </Group>
  );
}
