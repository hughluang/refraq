"use client";

import { Suspense } from "react";
import { useParams } from "next/navigation";

import { PageBodySkeleton } from "@/components/feedback/PageBodySkeleton";
import { SourceRecord } from "@/features/sources/SourceRecord";

export default function SourceDetailPage() {
  const params = useParams<{ id: string }>();
  return (
    <Suspense fallback={<PageBodySkeleton />}>
      <SourceRecord mode="show" sourceId={params.id} />
    </Suspense>
  );
}
