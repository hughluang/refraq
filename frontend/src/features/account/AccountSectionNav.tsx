"use client";

import { Button, Stack } from "@mantine/core";
import { useCan, useTranslate } from "@refinedev/core";
import { useEffect, useMemo, useRef, useState } from "react";

import {
  ACCOUNT_SECTION,
  accountPageScrollRoot,
  activeAccountSection,
  observationFromEntry,
  scrollAccountSection,
  type AccountSectionObservation,
} from "@/features/account/account-sections";
import { ModuleAction, ModuleId } from "@/features/console/module-identity";

type TocItem = {
  id: string;
  label: string;
};

export function AccountSectionNav() {
  const t = useTranslate();
  const navRef = useRef<HTMLElement>(null);
  const { data: canTokens } = useCan({
    resource: ModuleId.tokens,
    action: ModuleAction.list,
  });
  const [activeId, setActiveId] = useState<string>(ACCOUNT_SECTION.profile);

  const items: TocItem[] = useMemo(() => {
    const next: TocItem[] = [
      { id: ACCOUNT_SECTION.profile, label: t("account.section.profile") },
    ];
    if (canTokens?.can) {
      next.push({ id: ACCOUNT_SECTION.tokens, label: t("tokens.title") });
    }
    next.push({ id: ACCOUNT_SECTION.mcp, label: t("account.mcp.title") });
    return next;
  }, [canTokens?.can, t]);

  const itemIds = items.map((item) => item.id).join(" ");

  useEffect(() => {
    if (typeof IntersectionObserver === "undefined") {
      return;
    }
    const nav = navRef.current;
    const root = accountPageScrollRoot(nav);
    if (!nav || !root) {
      return;
    }

    const latest = new Map<string, AccountSectionObservation>();
    const observer = new IntersectionObserver(
      (entries) => {
        for (const entry of entries) {
          const observation = observationFromEntry(entry);
          if (observation) {
            latest.set(observation.id, observation);
          }
        }
        const next = activeAccountSection([...latest.values()]);
        if (next) {
          setActiveId(next);
        }
      },
      {
        root,
        threshold: [0, 0.25, 0.5, 0.75, 1],
      },
    );

    const ids = itemIds.split(" ");
    for (const id of ids) {
      const target = document.getElementById(id);
      if (target) {
        observer.observe(target);
      }
    }

    return () => {
      observer.disconnect();
    };
  }, [itemIds]);

  return (
    <nav
      ref={navRef}
      aria-label={t("account.jump.nav")}
      style={{
        position: "sticky",
        top: 0,
        flexShrink: 0,
        alignSelf: "flex-start",
        width: "12.5rem",
      }}
    >
      <Stack gap={4}>
        {items.map((item) => {
          const current = item.id === activeId;
          return (
            <Button
              key={item.id}
              type="button"
              variant={current ? "light" : "subtle"}
              size="compact-sm"
              justify="flex-start"
              aria-current={current ? "true" : undefined}
              onClick={() => scrollAccountSection(item.id)}
            >
              {item.label}
            </Button>
          );
        })}
      </Stack>
    </nav>
  );
}
