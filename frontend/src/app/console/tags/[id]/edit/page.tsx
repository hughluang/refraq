"use client";

import { Suspense } from "react";
import { useParams } from "next/navigation";

import { PageBodySkeleton } from "@/components/feedback/PageBodySkeleton";
import { TagRecord } from "@/features/tags/TagRecord";

export default function TagEditPage() {
  const params = useParams<{ id: string }>();
  return (
    <Suspense fallback={<PageBodySkeleton />}>
      <TagRecord mode="edit" tagId={params.id} />
    </Suspense>
  );
}
