"use client";

import { ConsoleRouteError } from "@/components/layout/ConsoleRouteError";

export default function ConsoleError({
  reset,
}: {
  error: Error & { digest?: string };
  reset: () => void;
}) {
  return <ConsoleRouteError reset={reset} />;
}
