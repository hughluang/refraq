"use client";

import { Suspense } from "react";

import { PageBodySkeleton } from "@/components/feedback/PageBodySkeleton";
import { SourceRecord } from "@/features/sources/SourceRecord";

export default function SourceCreatePage() {
  return (
    <Suspense fallback={<PageBodySkeleton />}>
      <SourceRecord mode="create" />
    </Suspense>
  );
}
