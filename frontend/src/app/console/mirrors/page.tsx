"use client";

import { Suspense } from "react";
import { PageBodySkeleton } from "@/components/feedback/PageBodySkeleton";
import { MirrorList } from "@/features/mirrors/MirrorList";

export default function MirrorsPage() {
  return <Suspense fallback={<PageBodySkeleton />}><MirrorList /></Suspense>;
}
