import { createTheme, rem, type CSSVariablesResolver, type MantineTheme } from "@mantine/core";

import { appTheme } from "@/features/branding/theme";
import {
  EASING,
  FEEDBACK_DELAY_MS,
  MOTION_MS,
  overlayTransition,
  TABLE_DENSITY,
} from "@/theme/tokens";

const TYPOGRAPHY = {
  fontSizes: {
    xs: rem(12),
    sm: rem(14),
    md: rem(16),
    lg: rem(18),
    xl: rem(20),
  },
  lineHeights: {
    xs: "1.4",
    sm: "1.45",
    md: "1.55",
    lg: "1.6",
    xl: "1.65",
  },
  headings: {
    sizes: {
      h1: { fontSize: rem(34), lineHeight: "1.3" },
      h2: { fontSize: rem(26), lineHeight: "1.35" },
      h3: { fontSize: rem(22), lineHeight: "1.4" },
      h4: { fontSize: rem(18), lineHeight: "1.45" },
      h5: { fontSize: rem(16), lineHeight: "1.5" },
      h6: { fontSize: rem(14), lineHeight: "1.5" },
    },
  },
} as const;

function shade(theme: MantineTheme, color: string, index: number): string {
  return theme.colors[color][index];
}

function toneVariables(theme: MantineTheme, scheme: "light" | "dark"): Record<string, string> {
  const solid = scheme === "light" ? 6 : 4;
  const soft = scheme === "light" ? 4 : 6;
  return {
    "--refraq-tone-neutral": shade(theme, "gray", solid),
    "--refraq-tone-neutral-muted":
      scheme === "light" ? shade(theme, "gray", 2) : shade(theme, "dark", 5),
    "--refraq-tone-neutral-border":
      scheme === "light" ? shade(theme, "gray", 3) : shade(theme, "dark", 4),
    "--refraq-tone-info": shade(theme, "blue", solid),
    "--refraq-tone-running": shade(theme, "cyan", solid),
    "--refraq-tone-success": shade(theme, "green", solid),
    "--refraq-tone-warning": shade(theme, "yellow", solid),
    "--refraq-tone-warning-soft": shade(theme, "yellow", soft),
    "--refraq-tone-danger": shade(theme, "red", solid),
    "--refraq-tone-danger-soft": shade(theme, "red", soft),
    "--refraq-tone-pinned": shade(theme, "grape", solid),
    "--refraq-tone-on-solid": theme.white,
  };
}

export function productTheme(primaryShades: readonly string[] | null | undefined) {
  return createTheme({
    ...appTheme(primaryShades),
    defaultRadius: "sm",
    radius: { pill: "999px" },
    focusRing: "auto",
    respectReducedMotion: true,
    ...TYPOGRAPHY,
    other: {
      motionMs: MOTION_MS,
      easing: EASING,
      feedbackDelayMs: FEEDBACK_DELAY_MS,
      tableDensity: TABLE_DENSITY,
    },
    components: {
      Badge: { defaultProps: { variant: "light" } },
      Button: {
        styles: {
          // Reduced motion skips the loader transition, which is the only
          // source of the centering translate. left/top 50% then pins the
          // spinner's top-left to the button center.
          loader: { transform: "translate(-50%, -50%)" },
        },
      },
      Tooltip: { defaultProps: { openDelay: FEEDBACK_DELAY_MS } },
      ActionIcon: { defaultProps: { variant: "subtle" } },
      Modal: { defaultProps: { transitionProps: overlayTransition } },
      Menu: { defaultProps: { transitionProps: overlayTransition } },
      Popover: { defaultProps: { transitionProps: overlayTransition } },
      Drawer: { defaultProps: { transitionProps: overlayTransition } },
    },
  });
}

export const productCssVariablesResolver: CSSVariablesResolver = (theme) => ({
  variables: {
    "--refraq-motion-fast": `${MOTION_MS.fast}ms`,
    "--refraq-motion-base": `${MOTION_MS.base}ms`,
    "--refraq-motion-slow": `${MOTION_MS.slow}ms`,
    "--refraq-ease-standard": EASING.standard,
    "--refraq-ease-enter": EASING.enter,
    "--refraq-ease-exit": EASING.exit,
    "--refraq-feedback-delay": `${FEEDBACK_DELAY_MS}ms`,
  },
  light: {
    ...toneVariables(theme, "light"),
    "--mantine-color-dimmed": shade(theme, "gray", 7),
    "--mantine-color-placeholder": shade(theme, "gray", 7),
    "--mantine-color-anchor": shade(theme, "blue", 8),
  },
  dark: {
    ...toneVariables(theme, "dark"),
    "--mantine-color-dimmed": shade(theme, "dark", 1),
    "--mantine-color-placeholder": shade(theme, "dark", 1),
  },
});
