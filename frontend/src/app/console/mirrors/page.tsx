"use client";

import { Suspense } from "react";
import { PageBodySkeleton } from "@/components/feedback/PageBodySkeleton";
import { FleetOverview } from "@/features/mirrors/FleetOverview";

export default function MirrorsPage() {
  return <Suspense fallback={<PageBodySkeleton />}><FleetOverview /></Suspense>;
}
