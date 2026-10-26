"use client";

import { Suspense } from "react";
import { useParams } from "next/navigation";

import { PageBodySkeleton } from "@/components/feedback/PageBodySkeleton";
import { TagRecord } from "@/features/tags/TagRecord";

export default function TagDetailPage() {
  const params = useParams<{ id: string }>();
  return (
    <Suspense fallback={<PageBodySkeleton />}>
      <TagRecord mode="show" tagId={params.id} />
    </Suspense>
  );
}
