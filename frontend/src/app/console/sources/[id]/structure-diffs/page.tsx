"use client";

import { useParams } from "next/navigation";

import { StructureDiffList } from "@/features/sources/structure-diffs/StructureDiffList";

export default function SourceStructureDiffsPage() {
  const params = useParams<{ id: string }>();
  return <StructureDiffList sourceId={params.id} />;
}
