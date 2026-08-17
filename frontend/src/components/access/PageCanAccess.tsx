"use client";

import { useCan } from "@refinedev/core";
import type { ReactNode } from "react";
import { usePathname } from "next/navigation";

import { ForbiddenState } from "@/components/feedback/ForbiddenState";
import { PageBodySkeleton } from "@/components/feedback/PageBodySkeleton";
import {
  matchPath,
  useModuleIdentityStore,
} from "@/features/console/module-identity";
import { useSessionStore } from "@/providers/session-store";

type PageCanAccessProps = {
  children: ReactNode;
};

export function PageCanAccess({ children }: PageCanAccessProps) {
  const pathname = usePathname();
  const modules = useModuleIdentityStore((state) => state.modules);
  const status = useModuleIdentityStore((state) => state.status);
  const permissionsReady = useSessionStore((state) => state.permissionsReady);
  const ready = permissionsReady && status === "ready";
  const matched = ready ? matchPath(pathname, modules) : null;

  const { data, isLoading } = useCan({
    resource: matched?.resource ?? "",
    action: matched?.action ?? "list",
    queryOptions: { enabled: ready && matched !== null },
  });

  if (!ready) {
    return <PageBodySkeleton />;
  }

  if (!matched) {
    return children;
  }

  if (isLoading || data === undefined) {
    return <PageBodySkeleton />;
  }

  if (!data.can) {
    return <ForbiddenState reason={data.reason} />;
  }

  return children;
}
