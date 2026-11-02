"use client";

import { Suspense } from "react";
import { useParams } from "next/navigation";

import { PageBodySkeleton } from "@/components/feedback/PageBodySkeleton";
import { SourceRecord } from "@/features/sources/SourceRecord";

export default function SourceEditPage() {
  const params = useParams<{ id: string }>();
  return (
    <Suspense fallback={<PageBodySkeleton />}>
      <SourceRecord mode="edit" sourceId={params.id} />
    </Suspense>
  );
}
