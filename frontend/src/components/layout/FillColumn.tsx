"use client";

import { Flex, type FlexProps } from "@mantine/core";
import type { ReactNode } from "react";

type FillColumnProps = {
  children?: ReactNode;
  gap?: FlexProps["gap"];
  /** Shrink floor. Defaults to 0 so leftover space can collapse; never `auto`. */
  minHeight?: FlexProps["mih"];
};

/**
 * Remaining-space frame: a flex column that consumes leftover block size
 * from its parent. Intrinsic siblings keep their height; this box shrinks
 * and grows. Children that should fill it (for example `ListTable`) also
 * need `flex: 1` and `min-height: 0`. Direction, flex, and shrink-below-content
 * are the contract; this is not a Flex alias.
 */
export function FillColumn({
  children,
  gap,
  minHeight = 0,
}: FillColumnProps) {
  return (
    <Flex direction="column" flex={1} mih={minHeight} gap={gap}>
      {children}
    </Flex>
  );
}
