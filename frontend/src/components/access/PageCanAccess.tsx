"use client";

import { useCan, useTranslate } from "@refinedev/core";
import type { ReactNode } from "react";
import { usePathname } from "next/navigation";

import { PageChrome } from "@/components/layout/PageChrome";
import { useBranding } from "@/features/branding/BrandingProvider";
import {
  matchPath,
  useModuleIdentityStore,
} from "@/features/console/module-identity";
import { useSessionStore } from "@/providers/session-store";

type PageCanAccessProps = {
  children: ReactNode;
};

export function PageCanAccess({ children }: PageCanAccessProps) {
  const t = useTranslate();
  const brandName = useBranding().brandName;
  const pathname = usePathname();
  const modules = useModuleIdentityStore((state) => state.modules);
  const status = useModuleIdentityStore((state) => state.status);
  const permissionsReady = useSessionStore((state) => state.permissionsReady);
  const ready = permissionsReady && status === "ready";
  const matched = matchPath(pathname, modules);
  const labelKey = matched
    ? modules.find((module) => module.id === matched.resource)?.label_key
    : undefined;
  const moduleTitle = labelKey ? t(labelKey) : brandName || t("layout.nav.home");

  const { data, isLoading } = useCan({
    resource: matched?.resource ?? "",
    action: matched?.action ?? "list",
    queryOptions: { enabled: ready && matched !== null },
  });

  if (!ready) {
    return <PageChrome title={moduleTitle} status="loading" />;
  }

  if (!matched) {
    return <PageChrome title={moduleTitle} status="notFound" />;
  }

  if (isLoading || data === undefined) {
    return <PageChrome title={moduleTitle} status="loading" />;
  }

  if (!data.can) {
    return (
      <PageChrome
        title={moduleTitle}
        status="forbidden"
        forbiddenReason={data.reason}
      />
    );
  }

  return children;
}
