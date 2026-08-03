"use client";

import { Refine } from "@refinedev/core";
import routerProvider from "@refinedev/nextjs-router";
import { useChangeLanguage } from "next-i18next/client";
import type { ReactNode } from "react";
import { useTranslation } from "react-i18next";

import { accessControlProvider } from "@/providers/access-control-provider";
import { authProvider } from "@/providers/auth-provider";
import { dataProvider } from "@/providers/data-provider";
import { createI18nProvider } from "@/providers/i18n-provider";
import { bindClientI18n } from "@/providers/i18n-runtime";
import { LOCALE_COOKIE_NAME } from "@/providers/locale-catalog";
import { notificationProvider } from "@/providers/notification-provider";

type RefineRootProps = { children: ReactNode };

export function RefineRoot({ children }: RefineRootProps) {
  const { t, i18n } = useTranslation("common");
  const changeLanguage = useChangeLanguage(LOCALE_COOKIE_NAME);
  bindClientI18n(i18n);
  const i18nProvider = createI18nProvider(t, i18n, changeLanguage);

  return (
    <Refine
      dataProvider={dataProvider}
      authProvider={authProvider}
      accessControlProvider={accessControlProvider}
      routerProvider={routerProvider}
      i18nProvider={i18nProvider}
      notificationProvider={notificationProvider}
      resources={[
        {
          name: "dashboard",
          list: "/console",
          meta: { label: "layout.nav.home", icon: undefined },
        },
        {
          name: "users",
          list: "/console/users",
          create: "/console/users/new",
          meta: { label: "users.title" },
        },
        {
          name: "roles",
          list: "/console/roles",
          create: "/console/roles/new",
          edit: "/console/roles/:id",
          meta: { label: "roles.title" },
        },
      ]}
      options={{
        syncWithLocation: true,
        warnWhenUnsavedChanges: true,
        disableRouteChangeHandler: true,
      }}
    >
      {children}
    </Refine>
  );
}
