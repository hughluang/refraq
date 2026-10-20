"use client";

import {
  Box,
  Button,
  Menu,
  useMantineColorScheme,
  type MantineColorScheme,
} from "@mantine/core";
import { useTranslate } from "@refinedev/core";
import { useEffect, type ReactNode } from "react";

import "./ColorSchemeControl.css";
import { COLOR_SCHEME_PREFERENCE_ATTRIBUTE } from "@/components/MantineColorSchemeScript";
import { DesktopIcon, MoonIcon, SunIcon } from "@/components/icons";

const CHOICES: MantineColorScheme[] = ["light", "dark", "auto"];

function publishPreference(scheme: MantineColorScheme) {
  document.documentElement.setAttribute(COLOR_SCHEME_PREFERENCE_ATTRIBUTE, scheme);
}

function isColorScheme(value: string): value is MantineColorScheme {
  return value === "light" || value === "dark" || value === "auto";
}

function SchemeIcon({ scheme }: { scheme: MantineColorScheme }) {
  if (scheme === "dark") return <MoonIcon size={14} />;
  if (scheme === "auto") return <DesktopIcon size={14} />;
  return <SunIcon size={14} />;
}

function choiceKey(scheme: MantineColorScheme): string {
  return scheme === "auto" ? "colorScheme.system" : `colorScheme.${scheme}`;
}

function PreferenceOption({
  scheme,
  children,
}: {
  scheme: MantineColorScheme;
  children: ReactNode;
}) {
  return (
    <Box
      component="span"
      className="color-scheme-option"
      data-color-scheme-option={scheme}
    >
      {children}
    </Box>
  );
}

export function ColorSchemeControl() {
  const t = useTranslate();
  const { colorScheme, setColorScheme } = useMantineColorScheme();

  useEffect(() => {
    publishPreference(colorScheme);
  }, [colorScheme]);

  function selectScheme(value: string) {
    if (!isColorScheme(value)) return;
    publishPreference(value);
    setColorScheme(value);
  }

  return (
    <Menu position="bottom-end" withinPortal>
      <Menu.Target>
        <Button
          variant="subtle"
          size="compact-sm"
          leftSection={
            <>
              <PreferenceOption scheme="light">
                <SunIcon size={14} />
              </PreferenceOption>
              <PreferenceOption scheme="dark">
                <MoonIcon size={14} />
              </PreferenceOption>
              <PreferenceOption scheme="auto">
                <DesktopIcon size={14} />
              </PreferenceOption>
            </>
          }
          aria-label={t("colorScheme.label")}
        >
          <PreferenceOption scheme="light">{t("colorScheme.light")}</PreferenceOption>
          <PreferenceOption scheme="dark">{t("colorScheme.dark")}</PreferenceOption>
          <PreferenceOption scheme="auto">{t("colorScheme.system")}</PreferenceOption>
        </Button>
      </Menu.Target>
      <Menu.Dropdown>
        <Menu.RadioGroup value={colorScheme} onChange={selectScheme}>
          {CHOICES.map((choice) => (
            <Menu.RadioItem key={choice} value={choice} closeMenuOnClick>
              <span className="color-scheme-choice">
                <SchemeIcon scheme={choice} />
                {t(choiceKey(choice))}
              </span>
            </Menu.RadioItem>
          ))}
        </Menu.RadioGroup>
      </Menu.Dropdown>
    </Menu>
  );
}
