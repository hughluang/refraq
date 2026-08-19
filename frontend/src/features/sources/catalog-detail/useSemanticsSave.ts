"use client";

import { useNotification, useTranslate } from "@refinedev/core";
import { useState } from "react";

import type { CatalogObject } from "@/features/sources/types";
import { ApiError } from "@/lib/api";

export function useSemanticsSave(onSaved: (object: CatalogObject) => void) {
  const t = useTranslate();
  const { open } = useNotification();
  const [saving, setSaving] = useState(false);

  const save = async (
    work: () => Promise<{ object: CatalogObject }>,
  ): Promise<CatalogObject | undefined> => {
    setSaving(true);
    try {
      const data = await work();
      onSaved(data.object);
      open?.({ type: "success", message: t("catalog.semantics.saved") });
      return data.object;
    } catch (err) {
      open?.({
        type: "error",
        message: err instanceof ApiError ? err.detail : String(err),
      });
      return undefined;
    } finally {
      setSaving(false);
    }
  };

  return { saving, save };
}
