export function commandPaletteShortcut(): string {
  if (typeof navigator === "undefined") return "Ctrl K";
  const platform = navigator.platform ?? "";
  const agent = navigator.userAgent ?? "";
  if (/Mac|iPhone|iPad|iPod/.test(platform) || /Mac OS/.test(agent)) {
    return "⌘ K";
  }
  return "Ctrl K";
}
