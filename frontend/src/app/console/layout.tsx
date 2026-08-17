"use client";

import { useGo, useIsAuthenticated } from "@refinedev/core";
import { useEffect, type ReactNode } from "react";

import { PageCanAccess } from "@/components/access/PageCanAccess";
import { ConsoleShell } from "@/components/layout/ConsoleShell";
import { ModuleIdentityGate } from "@/features/console/module-identity";

/**
 * Renders ConsoleShell unless check has confirmed unauthenticated.
 * Relies on authProvider.check() resolving without awaiting /auth/me so
 * Refine Authenticated does not flash a full-page loader over the shell.
 */
export default function ConsoleLayout({ children }: { children: ReactNode }) {
  const { data, isFetching } = useIsAuthenticated();
  const go = useGo();

  const denied = !isFetching && data !== undefined && !data.authenticated;

  useEffect(() => {
    if (!denied) return;
    go({ to: data.redirectTo ?? "/login", type: "replace" });
  }, [data, denied, go]);

  if (denied) {
    return null;
  }

  return (
    <ConsoleShell>
      <ModuleIdentityGate>
        <PageCanAccess>{children}</PageCanAccess>
      </ModuleIdentityGate>
    </ConsoleShell>
  );
}
