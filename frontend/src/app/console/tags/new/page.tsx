"use client";

import { Suspense } from "react";

import { PageBodySkeleton } from "@/components/feedback/PageBodySkeleton";
import { TagRecord } from "@/features/tags/TagRecord";

export default function TagCreatePage() {
  return (
    <Suspense fallback={<PageBodySkeleton />}>
      <TagRecord mode="create" />
    </Suspense>
  );
}
