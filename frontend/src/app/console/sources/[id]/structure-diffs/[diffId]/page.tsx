"use client";

import { useParams } from "next/navigation";

import { StructureDiffDetail } from "@/features/sources/structure-diffs/StructureDiffDetail";

export default function SourceStructureDiffDetailPage() {
  const params = useParams<{ id: string; diffId: string }>();
  return (
    <StructureDiffDetail sourceId={params.id} diffId={params.diffId} />
  );
}
