import {
  createTheme,
  type MantineColorsTuple,
} from "@mantine/core";

export function appTheme(primaryShades: readonly string[] | null | undefined) {
  const brandShades =
    primaryShades?.length === 10
      ? (primaryShades as unknown as MantineColorsTuple)
      : null;
  return createTheme({
    primaryColor: brandShades ? "brand" : "blue",
    ...(brandShades ? { colors: { brand: brandShades } } : {}),
    autoContrast: true,
  });
}
