export function isHexColor(value: string): boolean {
  return /^#[0-9a-f]{6}$/i.test(value);
}

function channelToLinear(channel: number): number {
  const value = channel / 255;
  return value <= 0.04045
    ? value / 12.92
    : ((value + 0.055) / 1.055) ** 2.4;
}

export function relativeLuminance(hex: string): number {
  if (!isHexColor(hex)) {
    throw new Error("relativeLuminance requires a six-digit hex color");
  }
  const red = channelToLinear(Number.parseInt(hex.slice(1, 3), 16));
  const green = channelToLinear(Number.parseInt(hex.slice(3, 5), 16));
  const blue = channelToLinear(Number.parseInt(hex.slice(5, 7), 16));
  return 0.2126 * red + 0.7152 * green + 0.0722 * blue;
}

export function warnsInsufficientCustomContrast(
  primaryColor: string,
  ratio: number,
): boolean {
  return isHexColor(primaryColor) && ratio < 4.5;
}

export function contrastRatio(background: string): {
  foreground: "#000000" | "#ffffff";
  ratio: number;
} {
  const luminance = relativeLuminance(background);
  const foreground = luminance > 0.3 ? "#000000" : "#ffffff";
  const foregroundLuminance = foreground === "#000000" ? 0 : 1;
  const ratio =
    (Math.max(luminance, foregroundLuminance) + 0.05)
    / (Math.min(luminance, foregroundLuminance) + 0.05);
  return { foreground, ratio };
}
