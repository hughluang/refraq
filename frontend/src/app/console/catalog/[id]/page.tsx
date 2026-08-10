"use client";

import { useParams } from "next/navigation";

import { CatalogObjectDetail } from "@/features/sources/catalog-detail/CatalogObjectDetail";

export default function CatalogObjectPage() {
  const params = useParams<{ id: string }>();
  return <CatalogObjectDetail objectId={params.id} />;
}
