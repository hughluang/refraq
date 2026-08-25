"use client";

import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useState,
  type ReactNode,
} from "react";
import { useTranslation } from "react-i18next";

import {
  browserAssetUrl,
  resolveBranding,
} from "@/features/branding/resolve";
import type {
  PublicBranding,
  ResolvedBranding,
} from "@/features/branding/types";
import {
  getDefaultLocale,
  isLocale,
  SUPPORTED_LOCALES,
} from "@/providers/locale-catalog";

export type BrandingContextValue = ResolvedBranding & {
  raw: PublicBranding;
  logoUrl: string | null;
  replaceBranding: (next: PublicBranding) => void;
};

const BrandingContext = createContext<BrandingContextValue | null>(null);

export function BrandingProvider({
  branding,
  children,
}: {
  branding: PublicBranding;
  children: ReactNode;
}) {
  const { i18n, t } = useTranslation();
  const language = i18n.resolvedLanguage ?? i18n.language;
  const locale = isLocale(language) ? language : getDefaultLocale();
  const [current, setCurrent] = useState(branding);

  useEffect(() => {
    setCurrent(branding);
  }, [branding]);

  const replaceBranding = useCallback((next: PublicBranding) => {
    setCurrent(next);
  }, []);

  const value = useMemo<BrandingContextValue>(() => {
    const resolved = resolveBranding(
      current,
      locale,
      t("app.description"),
      getDefaultLocale(),
      SUPPORTED_LOCALES,
    );
    return {
      ...resolved,
      raw: current,
      logoUrl:
        current.show_logo === false
          ? null
          : browserAssetUrl(current.logo_url),
      replaceBranding,
    };
  }, [current, locale, replaceBranding, t]);

  useEffect(() => {
    document.title = value.brandName;
  }, [value.brandName]);

  return (
    <BrandingContext.Provider value={value}>
      {children}
    </BrandingContext.Provider>
  );
}

export function useBranding(): BrandingContextValue {
  const value = useContext(BrandingContext);
  if (!value) {
    throw new Error("useBranding must be used inside BrandingProvider");
  }
  return value;
}
