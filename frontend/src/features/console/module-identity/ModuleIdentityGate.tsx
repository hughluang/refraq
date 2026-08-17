"use client";

import { useTranslate } from "@refinedev/core";
import type { ReactNode } from "react";
import { useEffect } from "react";

import { ForbiddenState } from "@/components/feedback/ForbiddenState";
import { PageError } from "@/components/feedback/PageError";
import { useModuleIdentityStore } from "@/features/console/module-identity/store";

type ModuleIdentityGateProps = {
  children: ReactNode;
};

/**
 * Starts Console Module Identity bootstrap without blocking main content.
 * Errors become an explicit terminal state; loading leaves children mounted.
 */
export function ModuleIdentityGate({ children }: ModuleIdentityGateProps) {
  const t = useTranslate();
  const status = useModuleIdentityStore((state) => state.status);
  const error = useModuleIdentityStore((state) => state.error);
  const errorKind = useModuleIdentityStore((state) => state.errorKind);
  const load = useModuleIdentityStore((state) => state.load);

  useEffect(() => {
    if (status === "idle") {
      void load();
    }
  }, [status, load]);

  if (status === "error" && errorKind === "forbidden") {
    return <ForbiddenState reason="console:access" />;
  }

  if (status === "error") {
    return (
      <PageError
        message={
          error === "module_identity_load_failed"
            ? t("common.error.loadFailed")
            : error!
        }
        onRetry={() => void load()}
      />
    );
  }

  return children;
}
