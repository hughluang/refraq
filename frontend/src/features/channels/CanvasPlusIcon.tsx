"use client";

export const CANVAS_PLUS_PATH = "M7 3v8M3 7h8";

export function CanvasPlusIcon() {
  return (
    <svg
      className="channel-canvas-plus"
      width="14"
      height="14"
      viewBox="0 0 14 14"
      fill="none"
      aria-hidden
    >
      <path
        d={CANVAS_PLUS_PATH}
        stroke="currentColor"
        strokeWidth="1.5"
        strokeLinecap="round"
      />
    </svg>
  );
}
