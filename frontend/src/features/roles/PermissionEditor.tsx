"use client";

import { Checkbox, Group, Stack, Text, TextInput } from "@mantine/core";
import { useTranslate } from "@refinedev/core";
import { useMemo, useState } from "react";

import { RecordReference } from "@/components/display/RecordReference";
import { GENERATED_MODULE_CATALOG } from "@/features/console/module-identity/generated-catalog";
import { groupPermissions } from "@/features/roles/permissionGroups";
import type { PermissionCatalogEntry } from "@/features/roles/types";

type Props = {
  catalog: readonly PermissionCatalogEntry[];
  selected: readonly string[];
  locked: boolean;
  onChange: (next: string[]) => void;
};

export function PermissionEditor({ catalog, selected, locked, onChange }: Props) {
  const t = useTranslate();
  const [permissionFilter, setPermissionFilter] = useState("");
  const groups = useMemo(
    () => groupPermissions(catalog, GENERATED_MODULE_CATALOG),
    [catalog],
  );
  const query = permissionFilter.trim().toLowerCase();
  const chosen = useMemo(() => new Set(selected), [selected]);

  function permissionMatches(entry: PermissionCatalogEntry): boolean {
    if (!query) return true;
    return (
      entry.description.toLowerCase().includes(query) ||
      entry.key.toLowerCase().includes(query)
    );
  }

  function groupTitle(labelKey: string | null, id: string): string {
    if (labelKey) return t(labelKey);
    return id;
  }

  function setPermission(key: string, checked: boolean) {
    onChange(checked ? [...selected, key] : selected.filter((item) => item !== key));
  }

  function setGroup(keys: string[], checked: boolean) {
    const next = new Set(selected);
    for (const key of keys) {
      if (checked) next.add(key);
      else next.delete(key);
    }
    onChange([...next]);
  }

  return (
    <Stack gap="xs">
      <Text size="sm" fw={500}>
        {t("roles.fields.permissions")}
      </Text>
      <TextInput
        value={permissionFilter}
        placeholder={t("roles.permissions.filter")}
        aria-label={t("roles.permissions.filter")}
        onChange={(event) => setPermissionFilter(event.currentTarget.value)}
      />
      {groups.map((group) => {
        const entries = group.entries.filter((entry) => {
          if (locked && !chosen.has(entry.key)) return false;
          return permissionMatches(entry);
        });
        if (entries.length === 0) return null;
        const title = groupTitle(group.labelKey, group.id);
        const selectedCount = entries.filter((entry) => chosen.has(entry.key)).length;
        return (
          <Stack key={group.id} gap={4} role="group" aria-label={title}>
            <Text size="sm" fw={600}>
              {title}
            </Text>
            {locked ? null : (
              <Checkbox
                label={t("roles.permissions.selectAll")}
                checked={selectedCount === entries.length}
                indeterminate={selectedCount > 0 && selectedCount < entries.length}
                onChange={(event) =>
                  setGroup(
                    entries.map((entry) => entry.key),
                    event.currentTarget.checked,
                  )
                }
              />
            )}
            {entries.map((entry) =>
              locked ? (
                <RecordReference
                  key={entry.key}
                  name={entry.description}
                  recordKey={entry.key}
                />
              ) : (
                <Group key={entry.key} gap="xs" wrap="nowrap" align="center">
                  <Checkbox
                    aria-label={entry.description}
                    checked={chosen.has(entry.key)}
                    onChange={(event) =>
                      setPermission(entry.key, event.currentTarget.checked)
                    }
                  />
                  <RecordReference name={entry.description} recordKey={entry.key} />
                </Group>
              ),
            )}
          </Stack>
        );
      })}
    </Stack>
  );
}
