"use client";

import { Suspense } from "react";
import { useParams } from "next/navigation";

import { PageBodySkeleton } from "@/components/feedback/PageBodySkeleton";
import { DictionaryRecord } from "@/features/dictionaries/DictionaryRecord";

export default function DictionaryEditPage() {
  const params = useParams<{ id: string }>();
  return (
    <Suspense fallback={<PageBodySkeleton />}>
      <DictionaryRecord mode="edit" dictionaryId={params.id} />
    </Suspense>
  );
}
