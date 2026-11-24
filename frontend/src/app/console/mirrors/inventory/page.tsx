"use client";

import { Suspense } from "react";
import { PageBodySkeleton } from "@/components/feedback/PageBodySkeleton";
import { MirrorInventory } from "@/features/mirrors/MirrorInventory";

export default function InventoryPage() {
  return <Suspense fallback={<PageBodySkeleton />}><MirrorInventory /></Suspense>;
}
