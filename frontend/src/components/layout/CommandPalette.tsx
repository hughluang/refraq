"use client";

import "@mantine/spotlight/styles.css";

import {
  Group,
  Kbd,
  Text,
  useMantineColorScheme,
  type MantineColorScheme,
} from "@mantine/core";
import { Spotlight } from "@mantine/spotlight";
import { useCan, useTranslate } from "@refinedev/core";
import { useCallback, useEffect, useMemo, useRef, useState, type ReactNode } from "react";

import { useAccountLocale } from "@/components/accountLocale";
import { moduleIcon } from "@/components/icons";
import { commandPaletteShortcut } from "@/components/layout/paletteControl";
import { useConsoleNavData } from "@/components/layout/consoleNavData";
import {
  createRoute,
  PALETTE_RECORD_MODULES,
  PALETTE_SEARCH_DEBOUNCE_MS,
  searchPaletteRecords,
  type PaletteRecordHit,
} from "@/components/layout/paletteRecords";
import { useConsoleNavigation } from "@/components/navigation/useConsoleNavigation";
import { useModuleIdentityStore } from "@/features/console/module-identity";
import type { ModuleIdentity } from "@/features/console/module-identity/types";
import { RECENTS_PALETTE_LIMIT, readRecents, subscribeRecents } from "@/lib/recents";
import { useSessionStore } from "@/providers/session-store";

const SCHEMES: MantineColorScheme[] = ["light", "dark", "auto"];

function nextScheme(current: MantineColorScheme): MantineColorScheme {
  const index = SCHEMES.indexOf(current);
  return SCHEMES[(index + 1) % SCHEMES.length];
}

function schemeKey(scheme: MantineColorScheme): string {
  return scheme === "auto" ? "colorScheme.system" : `colorScheme.${scheme}`;
}

function usePaletteRecents(userId: string | undefined) {
  const [items, setItems] = useState(() =>
    userId ? readRecents(userId).slice(0, RECENTS_PALETTE_LIMIT) : [],
  );
  useEffect(() => {
    setItems(userId ? readRecents(userId).slice(0, RECENTS_PALETTE_LIMIT) : []);
    if (!userId) return;
    return subscribeRecents(() =>
      setItems(readRecents(userId).slice(0, RECENTS_PALETTE_LIMIT)),
    );
  }, [userId]);
  return items;
}

function useAccessQueryOptions() {
  const permissionsReady = useSessionStore((state) => state.permissionsReady);
  const identitiesReady = useModuleIdentityStore((state) => state.status === "ready");
  return { enabled: permissionsReady && identitiesReady };
}

function useRecordModuleIds() {
  const accessQuery = useAccessQueryOptions();
  const users = useCan({ resource: "users", action: "list", queryOptions: accessQuery });
  const roles = useCan({ resource: "roles", action: "list", queryOptions: accessQuery });
  const sources = useCan({ resource: "sources", action: "list", queryOptions: accessQuery });
  const entities = useCan({ resource: "entities", action: "list", queryOptions: accessQuery });
  const dictionaries = useCan({
    resource: "dictionaries",
    action: "list",
    queryOptions: accessQuery,
  });
  const tags = useCan({
    resource: "tags",
    action: "list",
    queryOptions: accessQuery,
  });
  const channels = useCan({ resource: "channels", action: "list", queryOptions: accessQuery });
  const groups = useCan({
    resource: "user-groups",
    action: "list",
    queryOptions: accessQuery,
  });
  const usersCan = users.data?.can === true;
  const rolesCan = roles.data?.can === true;
  const sourcesCan = sources.data?.can === true;
  const entitiesCan = entities.data?.can === true;
  const dictionariesCan = dictionaries.data?.can === true;
  const tagsCan = tags.data?.can === true;
  const channelsCan = channels.data?.can === true;
  const groupsCan = groups.data?.can === true;
  return useMemo(() => {
    const allowed: Record<string, boolean> = {
      users: usersCan,
      roles: rolesCan,
      sources: sourcesCan,
      entities: entitiesCan,
      dictionaries: dictionariesCan,
      tags: tagsCan,
      channels: channelsCan,
      "user-groups": groupsCan,
    };
    return PALETTE_RECORD_MODULES.filter((id) => allowed[id]);
  }, [
    usersCan,
    rolesCan,
    sourcesCan,
    entitiesCan,
    dictionariesCan,
    tagsCan,
    channelsCan,
    groupsCan,
  ]);
}

function CreateProbe({
  moduleId,
  onResult,
}: {
  moduleId: string;
  onResult: (moduleId: string, can: boolean) => void;
}) {
  const accessQuery = useAccessQueryOptions();
  const { data, isLoading } = useCan({
    resource: moduleId,
    action: "create",
    queryOptions: accessQuery,
  });
  useEffect(() => {
    if (isLoading || data == null) return;
    onResult(moduleId, data.can === true);
  }, [data, isLoading, moduleId, onResult]);
  return null;
}

function PaletteSection({ label, children }: { label: string; children: ReactNode }) {
  return (
    <>
      <Text size="xs" tt="uppercase" fw={700} c="dimmed" px="md" mt="sm">
        {label}
      </Text>
      {children}
    </>
  );
}

function matches(query: string, ...parts: string[]): boolean {
  const needle = query.trim().toLowerCase();
  if (!needle) return true;
  return parts.some((part) => part.toLowerCase().includes(needle));
}

export function CommandPalette() {
  const t = useTranslate();
  const { push } = useConsoleNavigation();
  const { groups, toggleNavigation } = useConsoleNavData();
  const identities = useModuleIdentityStore((state) => state.modules);
  const userId = useSessionStore((state) => state.user?.id);
  const recents = usePaletteRecents(userId);
  const recordModules = useRecordModuleIds();
  const { colorScheme, setColorScheme } = useMantineColorScheme();
  const { otherLocale, otherLabel, selectLocale } = useAccountLocale();
  const [query, setQuery] = useState("");
  const [records, setRecords] = useState<PaletteRecordHit[]>([]);
  const [recordsFailed, setRecordsFailed] = useState(false);
  const [createAllowed, setCreateAllowed] = useState<ReadonlySet<string>>(
    () => new Set(),
  );
  const generation = useRef(0);
  const recordKey = recordModules.join("\0");

  const onCreateResult = useCallback((moduleId: string, can: boolean) => {
    setCreateAllowed((current) => {
      const has = current.has(moduleId);
      if (has === can) return current;
      const next = new Set(current);
      if (can) next.add(moduleId);
      else next.delete(moduleId);
      return next;
    });
  }, []);

  const identityById = useMemo(() => {
    const map = new Map<string, ModuleIdentity>();
    for (const module of identities) map.set(module.id, module);
    return map;
  }, [identities]);

  const createModules = useMemo(
    () =>
      identities.flatMap((module) => {
        const route = createRoute(module);
        return route === null ? [] : [{ module, route }];
      }),
    [identities],
  );

  useEffect(() => {
    const current = ++generation.current;
    const trimmed = query.trim();
    if (!trimmed || recordModules.length === 0) {
      setRecords([]);
      setRecordsFailed(false);
      return;
    }
    const controller = new AbortController();
    const timer = window.setTimeout(() => {
      void searchPaletteRecords({
        query: trimmed,
        moduleIds: recordModules,
        identities,
        signal: controller.signal,
      }).then((result) => {
        if (generation.current !== current) return;
        setRecords(result.hits);
        setRecordsFailed(result.failed);
      });
    }, PALETTE_SEARCH_DEBOUNCE_MS);
    return () => {
      window.clearTimeout(timer);
      controller.abort();
    };
  }, [query, recordKey, identities, recordModules]);

  const goTo = groups.flatMap((group) => group.modules);
  const visibleRecents = recents.filter((item) =>
    matches(query, item.title, moduleLabel(item.moduleId)),
  );
  const visibleGoTo = goTo.filter((module) => matches(query, t(module.label_key)));
  const visibleCreate = createModules.filter(({ module }) => {
    if (!createAllowed.has(module.id)) return false;
    const label = t("layout.palette.createItem", { module: t(module.label_key) });
    return matches(query, label);
  });
  const destination = nextScheme(colorScheme);
  const actions = [
    {
      id: "color-scheme",
      label: t("layout.palette.action.colorScheme"),
      description: t(schemeKey(destination)),
      onClick: () => setColorScheme(destination),
    },
    {
      id: "navigation",
      label: t("layout.palette.action.navigation"),
      description: "",
      onClick: toggleNavigation,
    },
    {
      id: "language",
      label: t("layout.palette.action.language"),
      description: otherLabel,
      onClick: () => {
        void selectLocale(otherLocale);
      },
    },
    {
      id: "account",
      label: t("layout.palette.action.account"),
      description: "",
      onClick: () => push("/console/account"),
    },
  ].filter((action) => matches(query, action.label, action.description));

  function moduleLabel(moduleId: string): string {
    const identity = identityById.get(moduleId);
    return identity ? t(identity.label_key) : "";
  }

  function iconFor(moduleId: string) {
    return moduleIcon(identityById.get(moduleId)?.icon);
  }

  const shortcut = commandPaletteShortcut();

  return (
    <>
      {createModules.map(({ module }) => (
        <CreateProbe key={module.id} moduleId={module.id} onResult={onCreateResult} />
      ))}
      <Spotlight.Root
        shortcut="mod+K"
        tagsToIgnore={[]}
        triggerOnContentEditable
        scrollable
        query={query}
        onQueryChange={setQuery}
        size="lg"
      >
        <Spotlight.Search
          placeholder={t("layout.palette.open")}
          aria-label={t("layout.palette.open")}
        />
        <Spotlight.ActionsList>
          {visibleRecents.length > 0 ? (
            <PaletteSection label={t("layout.palette.recent")}>
              {visibleRecents.map((item) => {
                const Icon = iconFor(item.moduleId);
                return (
                  <Spotlight.Action
                    key={item.href}
                    label={item.title}
                    description={moduleLabel(item.moduleId)}
                    leftSection={<Icon />}
                    onClick={() => push(item.href)}
                  />
                );
              })}
            </PaletteSection>
          ) : null}
          {visibleGoTo.length > 0 ? (
            <PaletteSection label={t("layout.palette.goTo")}>
              {visibleGoTo.map((module) => {
                const Icon = iconFor(module.id);
                const label = t(module.label_key);
                return (
                  <Spotlight.Action
                    key={module.id}
                    label={label}
                    leftSection={<Icon />}
                    onClick={() => push(module.route)}
                  />
                );
              })}
            </PaletteSection>
          ) : null}
          {visibleCreate.length > 0 ? (
            <PaletteSection label={t("layout.palette.create")}>
              {visibleCreate.map(({ module, route }) => {
                const Icon = iconFor(module.id);
                const label = t("layout.palette.createItem", {
                  module: t(module.label_key),
                });
                return (
                  <Spotlight.Action
                    key={module.id}
                    label={label}
                    leftSection={<Icon />}
                    onClick={() => push(route)}
                  />
                );
              })}
            </PaletteSection>
          ) : null}
          {query.trim() && recordsFailed ? (
            <Text size="sm" c="dimmed" px="sm" py={6}>
              {t("layout.palette.recordsFailed")}
            </Text>
          ) : null}
          {query.trim() && records.length > 0 ? (
            <PaletteSection label={t("layout.palette.records")}>
              {records.map((hit) => {
                const Icon = iconFor(hit.moduleId);
                return (
                  <Spotlight.Action
                    key={`${hit.moduleId}:${hit.id}`}
                    label={hit.title}
                    description={moduleLabel(hit.moduleId)}
                    leftSection={<Icon />}
                    onClick={() => push(hit.href)}
                  />
                );
              })}
            </PaletteSection>
          ) : null}
          {actions.length > 0 ? (
            <PaletteSection label={t("layout.palette.actions")}>
              {actions.map((action) => (
                <Spotlight.Action
                  key={action.id}
                  label={action.label}
                  description={action.description || undefined}
                  onClick={action.onClick}
                />
              ))}
            </PaletteSection>
          ) : null}
        </Spotlight.ActionsList>
        {query.trim() &&
        !recordsFailed &&
        visibleRecents.length === 0 &&
        visibleGoTo.length === 0 &&
        visibleCreate.length === 0 &&
        records.length === 0 &&
        actions.length === 0 ? (
          <Spotlight.Empty>{t("layout.palette.empty")}</Spotlight.Empty>
        ) : null}
        <Spotlight.Footer>
          <Group gap="md" wrap="wrap">
            <Text size="xs">
              <Kbd>{shortcut}</Kbd> {t("layout.palette.shortcut.palette")}
            </Text>
            <Text size="xs">
              <Kbd>/</Kbd> {t("layout.palette.shortcut.search")}
            </Text>
            <Text size="xs">
              <Kbd>[</Kbd> {t("layout.palette.shortcut.navigation")}
            </Text>
          </Group>
        </Spotlight.Footer>
      </Spotlight.Root>
    </>
  );
}
