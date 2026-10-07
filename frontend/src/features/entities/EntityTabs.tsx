"use client";

import { Tabs } from "@mantine/core";
import { useTranslate } from "@refinedev/core";
import type { ReactNode } from "react";

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
  showAccess?: boolean;
  showData?: boolean;
};

export function EntityTabs({
  value,
  onChange,
  overview,
  attributes,
  versions,
  access,
  data,
  showAccess = false,
  showData = false,
}: Props) {
  const t = useTranslate();

  return (
    <Tabs
      value={value}
      keepMounted
      onChange={(next) => onChange(parseEntityDetailTab(next))}
    >
      <Tabs.List>
        <Tabs.Tab value="overview">{t("entities.tabs.overview")}</Tabs.Tab>
        <Tabs.Tab value="attributes">{t("entities.tabs.attributes")}</Tabs.Tab>
        <Tabs.Tab value="versions">{t("entities.tabs.versions")}</Tabs.Tab>
        {showAccess ? (
          <Tabs.Tab value="access">{t("entities.tabs.access")}</Tabs.Tab>
        ) : null}
        {showData ? (
          <Tabs.Tab value="data">{t("entities.tabs.data")}</Tabs.Tab>
        ) : null}
      </Tabs.List>
      <Tabs.Panel value="overview" pt="md">
        {overview}
      </Tabs.Panel>
      <Tabs.Panel value="attributes" pt="md">
        {attributes}
      </Tabs.Panel>
      <Tabs.Panel value="versions" pt="md">
        {versions}
      </Tabs.Panel>
      {showAccess ? (
        <Tabs.Panel value="access" pt="md">
          {access}
        </Tabs.Panel>
      ) : null}
      {showData ? (
        <Tabs.Panel value="data" pt="md">
          {data}
        </Tabs.Panel>
      ) : null}
    </Tabs>
  );
}
