"use client";

import { useCan, useResourceParams } from "@refinedev/core";
import type { ReactNode } from "react";
import { usePathname } from "next/navigation";

import { ForbiddenState } from "@/components/feedback/ForbiddenState";
import { PageLoader } from "@/components/feedback/PageLoader";
import { matchResourceAction } from "@/lib/match-resource-action";

type PageCanAccessProps = {
  children: ReactNode;
};

export function PageCanAccess({ children }: PageCanAccessProps) {
  const pathname = usePathname();
  const { resources } = useResourceParams();
  const matched = matchResourceAction(pathname, resources);

  const { data, isLoading } = useCan({
    resource: matched?.resource ?? "",
    action: matched?.action ?? "list",
    queryOptions: { enabled: matched !== null },
  });

  // Non-resource console routes (e.g. not-found) are not ACL-gated.
  if (!matched) {
    return children;
  }

  if (isLoading || data === undefined) {
    return <PageLoader />;
  }

  if (!data.can) {
    return <ForbiddenState reason={data.reason} />;
  }

  return children;
}
