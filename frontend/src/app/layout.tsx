import type { Metadata } from "next";
import React from "react";

export const metadata: Metadata = {
  title: "refraq",
  description: "refraq data product integration platform",
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html lang="en-US">
      <body>{children}</body>
    </html>
  );
}
