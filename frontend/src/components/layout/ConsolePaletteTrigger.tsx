"use client";

import { ActionIcon, Button, Kbd } from "@mantine/core";
import { spotlight } from "@mantine/spotlight";
import { useTranslate } from "@refinedev/core";

import { SearchIcon } from "@/components/icons";
import { commandPaletteShortcut } from "@/components/layout/paletteControl";

export function ConsolePaletteTrigger() {
  const t = useTranslate();
  const shortcut = commandPaletteShortcut();
  const label = t("layout.palette.open");

  return (
    <>
      <Button
        variant="default"
        size="compact-sm"
        visibleFrom="sm"
        justify="space-between"
        leftSection={<SearchIcon />}
        rightSection={<Kbd>{shortcut}</Kbd>}
        onClick={() => spotlight.open()}
        aria-label={`${label} (${shortcut})`}
        miw={160}
        styles={{
          root: { fontWeight: 400 },
          inner: { justifyContent: "space-between", width: "100%" },
        }}
      >
        {label}
      </Button>
      <ActionIcon
        hiddenFrom="sm"
        variant="subtle"
        aria-label={`${label} (${shortcut})`}
        onClick={() => spotlight.open()}
      >
        <SearchIcon />
      </ActionIcon>
    </>
  );
}
