"use client";

import { Suspense } from "react";
import { useParams } from "next/navigation";

import { PageBodySkeleton } from "@/components/feedback/PageBodySkeleton";
import { EntityRecord } from "@/features/entities/EntityRecord";

export default function EntityDetailPage() {
  const params = useParams<{ id: string }>();
  return (
    <Suspense fallback={<PageBodySkeleton />}>
      <EntityRecord mode="show" entityId={params.id} />
    </Suspense>
  );
}
