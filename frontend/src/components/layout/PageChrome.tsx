"use client";

import { Box, Group, Stack, Text } from "@mantine/core";
import { useTranslate } from "@refinedev/core";
import { usePathname, useSearchParams } from "next/navigation";
import { useEffect, useLayoutEffect, type ReactNode } from "react";

import { ForbiddenState } from "@/components/feedback/ForbiddenState";
import { NotFoundState } from "@/components/feedback/NotFoundState";
import { PageBodySkeleton } from "@/components/feedback/PageBodySkeleton";
import { PageError } from "@/components/feedback/PageError";
import { PageBreadcrumb } from "@/components/layout/PageBreadcrumb";
import { SectionHeader } from "@/components/layout/SectionHeader";
import {
  setBrandDocumentTitle,
  setPageDocumentTitle,
} from "@/components/layout/documentTitle";
import { useBranding } from "@/features/branding/BrandingProvider";
import { matchPath } from "@/features/console/module-identity/adapters";
import { useModuleIdentityStore } from "@/features/console/module-identity/store";
import { rememberRecent, type RecentInput } from "@/lib/recents";
import { useSessionStore } from "@/providers/session-store";

export type PageStatus = "ready" | "loading" | "error" | "forbidden" | "notFound";

export type PageChromeProps = {
  title: string;
  /** Record name. Shown as the page heading; the module label stays in the document title. */
  recordTitle?: string;
  titleSlot?: ReactNode;
  titleExtra?: ReactNode;
  description?: string;
  descriptionLineClamp?: number;
  actions?: ReactNode;
  toolbar?: ReactNode;
  tabs?: ReactNode;
  /** Lock the column to the viewport so a fill child can take the leftover height. */
  fill?: boolean;
  status?: PageStatus;
  onRetry?: () => void;
  errorMessage?: string;
  requestId?: string | null;
  forbiddenReason?: string;
  /**
   * Explicit visit. `href` defaults to the current path and query.
   * Show and edit routes also record one when this is omitted.
   */
  recent?: {
    moduleId: string;
    title: string;
    href?: string;
  };
  children?: ReactNode;
};

const RECORD_ACTIONS = new Set(["show", "edit", "create"]);

export function PageChrome({
  title,
  recordTitle,
  titleSlot,
  titleExtra,
  description,
  descriptionLineClamp,
  actions,
  toolbar,
  tabs,
  fill = false,
  status = "ready",
  onRetry,
  errorMessage,
  requestId,
  forbiddenReason,
  recent,
  children,
}: PageChromeProps) {
  const t = useTranslate();
  const brandName = useBranding().brandName;
  const pathname = usePathname();
  const search = useSearchParams().toString();
  const locationHref = search ? `${pathname}?${search}` : pathname;
  const modules = useModuleIdentityStore((state) => state.modules);
  const userId = useSessionStore((state) => state.user?.id ?? null);
  const matched = modules.length > 0 ? matchPath(pathname, modules) : null;
  const matchedModule = matched
    ? modules.find((item) => item.id === matched.resource)
    : undefined;
  const routeLabel = matchedModule ? t(matchedModule.label_key) : "";
  const recordRoute = matched != null && RECORD_ACTIONS.has(matched.action);
  const showOrEdit = matched?.action === "show" || matched?.action === "edit";
  const explicitRecord = recordTitle?.trim() ?? "";
  const moduleLabel = title || routeLabel;
  const heading = explicitRecord || moduleLabel;
  const documentPage = documentPageTitle({
    title,
    recordTitle: explicitRecord,
    routeLabel,
    recordRoute,
  });
  const autoTitle =
    explicitRecord ||
    (showOrEdit && title && routeLabel && title !== routeLabel ? title : "");
  const visit: RecentInput | null = recent
    ? {
        moduleId: recent.moduleId,
        title: recent.title,
        href: recent.href ?? locationHref,
      }
    : showOrEdit && matched && autoTitle
      ? { moduleId: matched.resource, title: autoTitle, href: locationHref }
      : null;

  useLayoutEffect(() => {
    setBrandDocumentTitle(brandName);
    setPageDocumentTitle(documentPage || null);
    return () => setPageDocumentTitle(null);
  }, [brandName, documentPage]);

  const recentModuleId = visit?.moduleId;
  const recentTitle = visit?.title;
  const recentHref = visit?.href;
  useEffect(() => {
    if (!userId || !recentModuleId || !recentHref || !recentTitle) return;
    rememberRecent(userId, {
      moduleId: recentModuleId,
      title: recentTitle,
      href: recentHref,
    });
  }, [recentHref, recentModuleId, recentTitle, userId]);

  return (
    <Stack gap="md" flex={1} h="100%" mih={0} style={{ overflow: "hidden" }}>
      <Stack gap="md" data-page-header="" style={{ flex: "0 0 auto" }}>
        <PageBreadcrumb />
        <Group justify="space-between" align="flex-start" wrap="wrap" gap="sm">
          <Box style={{ flex: "1 1 16rem", minWidth: 0 }}>
            <SectionHeader
              title={heading}
              titleSlot={titleSlot}
              titleExtra={titleExtra}
              order={1}
              pageHeading
            />
          </Box>
          {actions ? (
            <Group gap="sm" wrap="wrap" align="center">
              {actions}
            </Group>
          ) : null}
        </Group>
        {description ? (
          <Text size="sm" c="dimmed" lineClamp={descriptionLineClamp}>
            {description}
          </Text>
        ) : null}
        {toolbar}
        {tabs}
      </Stack>
      <Stack
        gap="md"
        flex={1}
        mih={0}
        data-page-scroll=""
        style={{ overflow: fill ? "hidden" : "auto" }}
      >
        <PageStatusBody
          status={status}
          onRetry={onRetry}
          errorMessage={errorMessage ?? t("common.error.loadFailed")}
          requestId={requestId}
          forbiddenReason={forbiddenReason}
        >
          {children}
        </PageStatusBody>
      </Stack>
    </Stack>
  );
}

function documentPageTitle({
  title,
  recordTitle,
  routeLabel,
  recordRoute,
}: {
  title: string;
  recordTitle: string;
  routeLabel: string;
  recordRoute: boolean;
}) {
  if (recordTitle) {
    const mod = routeLabel || title;
    return mod && mod !== recordTitle ? `${recordTitle} · ${mod}` : recordTitle;
  }
  if (recordRoute && title && routeLabel && title !== routeLabel) {
    return `${title} · ${routeLabel}`;
  }
  return title || routeLabel;
}

function PageStatusBody({
  status,
  onRetry,
  errorMessage,
  requestId,
  forbiddenReason,
  children,
}: {
  status: PageStatus;
  onRetry?: () => void;
  errorMessage: string;
  requestId?: string | null;
  forbiddenReason?: string;
  children?: ReactNode;
}) {
  if (status === "loading") return <PageBodySkeleton />;
  if (status === "error") {
    return <PageError message={errorMessage} requestId={requestId} onRetry={onRetry} />;
  }
  if (status === "forbidden") return <ForbiddenState reason={forbiddenReason} />;
  if (status === "notFound") return <NotFoundState />;
  return children;
}
