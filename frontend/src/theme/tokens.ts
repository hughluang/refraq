/** Product motion, delay, and table-density tokens. Scheme-independent. */
export const MOTION_MS = {
  fast: 120,
  base: 200,
  slow: 300,
} as const;

export const EASING = {
  standard: "cubic-bezier(0.2, 0, 0, 1)",
  enter: "cubic-bezier(0, 0, 0.2, 1)",
  exit: "cubic-bezier(0.4, 0, 1, 1)",
} as const;

export const FEEDBACK_DELAY_MS = 200;

/** Density already used by collection tables. Table is not restyled globally. */
export const TABLE_DENSITY = {
  verticalSpacing: "xs",
  horizontalSpacing: "md",
} as const;

export const overlayTransition = {
  duration: MOTION_MS.base,
  exitDuration: MOTION_MS.base,
  timingFunction: EASING.standard,
} as const;
