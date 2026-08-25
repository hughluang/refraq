import "server-only";

import { cache } from "react";

import {
  DEFAULT_BRANDING,
  parsePublicBranding,
  type PublicBranding,
} from "@/features/branding/types";

export const getServerBranding = cache(async (): Promise<PublicBranding> => {
  try {
    const response = await fetch(
      `${process.env.REFRAQ_API_UPSTREAM ?? "http://127.0.0.1:8000"}/branding`,
      {
        signal: AbortSignal.timeout(2500),
        cache: "no-store",
      },
    );
    if (!response.ok) return DEFAULT_BRANDING;
    return parsePublicBranding(await response.json());
  } catch {
    return DEFAULT_BRANDING;
  }
});
