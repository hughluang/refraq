"use client";

import {
  Button,
  Menu,
  useMantineColorScheme,
  type MantineColorScheme,
} from "@mantine/core";
import { useTranslate } from "@refinedev/core";

import { DesktopIcon, MoonIcon, SunIcon } from "@/components/icons";

const CHOICES: MantineColorScheme[] = ["light", "dark", "auto"];

function SchemeIcon({ scheme }: { scheme: MantineColorScheme }) {
  if (scheme === "dark") return <MoonIcon size={14} />;
  if (scheme === "auto") return <DesktopIcon size={14} />;
  return <SunIcon size={14} />;
}

function choiceKey(scheme: MantineColorScheme): string {
  return scheme === "auto" ? "colorScheme.system" : `colorScheme.${scheme}`;
}

export function ColorSchemeControl() {
  const t = useTranslate();
  const { colorScheme, setColorScheme } = useMantineColorScheme();

  return (
    <Menu position="bottom-end" withinPortal>
      <Menu.Target>
        <Button
          variant="subtle"
          size="compact-sm"
          leftSection={<SchemeIcon scheme={colorScheme} />}
          aria-label={t("colorScheme.label")}
        >
          {t(choiceKey(colorScheme))}
        </Button>
      </Menu.Target>
      <Menu.Dropdown>
        {CHOICES.map((choice) => (
          <Menu.Item
            key={choice}
            leftSection={<SchemeIcon scheme={choice} />}
            aria-current={choice === colorScheme ? "true" : undefined}
            onClick={() => setColorScheme(choice)}
          >
            {t(choiceKey(choice))}
          </Menu.Item>
        ))}
      </Menu.Dropdown>
    </Menu>
  );
}
