"use client";

import { Authenticated } from "@refinedev/core";
import type { ReactNode } from "react";

import { PageCanAccess } from "@/components/access/PageCanAccess";
import { PageLoader } from "@/components/feedback/PageLoader";
import { ConsoleShell } from "@/components/layout/ConsoleShell";
import { ModuleIdentityGate } from "@/features/console/module-identity";

export default function ConsoleLayout({ children }: { children: ReactNode }) {
  return (
    <Authenticated
      key="console"
      redirectOnFail="/login"
      // Keep false: Refine `to` would make useLogin soft-navigate and race hard login nav.
      appendCurrentPathToQuery={false}
      loading={<PageLoader />}
    >
      <ConsoleShell>
        <ModuleIdentityGate>
          <PageCanAccess>{children}</PageCanAccess>
        </ModuleIdentityGate>
      </ConsoleShell>
    </Authenticated>
  );
}
