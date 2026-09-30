"use client";

import { Suspense } from "react";

import { PageBodySkeleton } from "@/components/feedback/PageBodySkeleton";
import { DictionaryRecord } from "@/features/dictionaries/DictionaryRecord";

export default function DictionaryCreatePage() {
  return (
    <Suspense fallback={<PageBodySkeleton />}>
      <DictionaryRecord mode="create" />
    </Suspense>
  );
}
