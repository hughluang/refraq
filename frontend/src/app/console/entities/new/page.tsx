"use client";

import { Suspense } from "react";

import { PageBodySkeleton } from "@/components/feedback/PageBodySkeleton";
import { EntityRecord } from "@/features/entities/EntityRecord";

export default function EntityCreatePage() {
  return (
    <Suspense fallback={<PageBodySkeleton />}>
      <EntityRecord mode="create" />
    </Suspense>
  );
}
