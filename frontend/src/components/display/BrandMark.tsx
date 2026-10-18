"use client";

import { Box, Image } from "@mantine/core";

type Props = {
  src: string;
  alt: string;
  height: number;
};

export function BrandMark({ src, alt, height }: Props) {
  return (
    <Box
      style={{
        display: "inline-flex",
        alignItems: "center",
        alignSelf: "flex-start",
        width: "fit-content",
        lineHeight: 0,
      }}
    >
      <Image src={src} alt={alt} h={height} w="auto" fit="contain" />
    </Box>
  );
}
