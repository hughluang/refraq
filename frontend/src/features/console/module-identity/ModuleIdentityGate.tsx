"use client";

import { useTranslate } from "@refinedev/core";
import type { ReactNode } from "react";
import { useEffect } from "react";

import { PageError } from "@/components/feedback/PageError";
import { PageLoader } from "@/components/feedback/PageLoader";
import { useModuleIdentityStore } from "@/features/console/module-identity/store";

type ModuleIdentityGateProps = {
  children: ReactNode;
};

/** Blocks main content until Console Module Identity bootstrap succeeds. */
export function ModuleIdentityGate({ children }: ModuleIdentityGateProps) {
  const t = useTranslate();
  const status = useModuleIdentityStore((state) => state.status);
  const error = useModuleIdentityStore((state) => state.error);
  const load = useModuleIdentityStore((state) => state.load);

  useEffect(() => {
    if (status === "idle") {
      void load();
    }
  }, [status, load]);

  if (status === "idle" || status === "loading") {
    return <PageLoader />;
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
