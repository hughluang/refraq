"use client";

import { useTranslate } from "@refinedev/core";
import type { ReactNode } from "react";

import { PageTabs, type PageTabItem } from "@/components/layout/consoleTabs";
import {
  parseEntityDetailTab,
  type EntityDetailTab,
} from "@/features/entities/entityDetailTab";

type Props = {
  value: EntityDetailTab;
  onChange: (tab: EntityDetailTab) => void;
  overview: ReactNode;
  attributes: ReactNode;
  versions: ReactNode;
  access?: ReactNode;
  data?: ReactNode;
  changeLog?: ReactNode;
  showAccess?: boolean;
  showData?: boolean;
  showChangeLog?: boolean;
  children: (slots: { list: ReactNode; panels: ReactNode }) => ReactNode;
};

export function EntityTabs({
  value,
  onChange,
  overview,
  attributes,
  versions,
  access,
  data,
  changeLog,
  showAccess = false,
  showData = false,
  showChangeLog = false,
  children,
}: Props) {
  const t = useTranslate();
  const tabs: PageTabItem[] = [
    { value: "overview", label: t("entities.tabs.overview"), panel: overview },
    { value: "attributes", label: t("entities.tabs.attributes"), panel: attributes },
    { value: "versions", label: t("entities.tabs.versions"), panel: versions },
  ];
  if (showAccess) {
    tabs.push({ value: "access", label: t("entities.tabs.access"), panel: access });
  }
  if (showData) {
    tabs.push({ value: "data", label: t("entities.tabs.data"), panel: data });
  }
  if (showChangeLog) {
    tabs.push({
      value: "change_log",
      label: t("entities.tabs.changeLog"),
      panel: changeLog,
    });
  }

  return (
    <PageTabs
      tabs={tabs}
      value={value}
      onChange={(next) => onChange(parseEntityDetailTab(next))}
    >
      {children}
    </PageTabs>
  );
}
