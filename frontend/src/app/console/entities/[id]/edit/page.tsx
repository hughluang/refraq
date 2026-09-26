"use client";

import { Suspense } from "react";
import { useParams } from "next/navigation";

import { PageBodySkeleton } from "@/components/feedback/PageBodySkeleton";
import { EntityRecord } from "@/features/entities/EntityRecord";

export default function EntityEditPage() {
  const params = useParams<{ id: string }>();
  return (
    <Suspense fallback={<PageBodySkeleton />}>
      <EntityRecord mode="edit" entityId={params.id} />
    </Suspense>
  );
}
